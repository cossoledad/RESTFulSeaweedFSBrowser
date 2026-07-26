import os
import posixpath
import shutil
import tempfile
import time
import urllib.error
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from .cancellation import CancellationToken
from .client import OperationCancelled, SeaweedClient
from .core import (
    APP_NAME,
    basename,
    get_path_extension,
    is_directory,
    normalize_dir_path,
    replace_extension,
    safe_local_path,
)
from .model_files import collect_gltf_resource_paths, sniff_model_format


class CancellableWorker(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.token = CancellationToken()

    def request_cancel(self) -> None:
        self.token.cancel()

    def is_cancelled(self) -> bool:
        return self.token.is_cancelled()


@dataclass
class ManagedTask:
    key: str
    thread: QThread
    worker: CancellableWorker


class TaskManager(QObject):
    task_finished = Signal(str)
    all_finished = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._tasks: Dict[str, ManagedTask] = {}

    def start(
        self,
        key: str,
        worker: CancellableWorker,
        terminal_signals: Iterable[Signal],
    ) -> ManagedTask:
        if key in self._tasks:
            raise RuntimeError(f"任务已经存在: {key}")
        thread = QThread(self)
        worker.moveToThread(thread)
        task = ManagedTask(key=key, thread=thread, worker=worker)
        self._tasks[key] = task
        thread.started.connect(worker.run)  # type: ignore[attr-defined]
        for signal in terminal_signals:
            signal.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda task_key=key: self._on_thread_finished(task_key))
        thread.start()
        return task

    def _on_thread_finished(self, key: str) -> None:
        self._tasks.pop(key, None)
        self.task_finished.emit(key)
        if not self._tasks:
            self.all_finished.emit()

    def get(self, key: str) -> Optional[ManagedTask]:
        return self._tasks.get(key)

    def contains(self, key: str) -> bool:
        return key in self._tasks

    def has_active_tasks(self) -> bool:
        return bool(self._tasks)

    def cancel(self, key: str) -> None:
        task = self._tasks.get(key)
        if task is not None:
            task.worker.request_cancel()

    def cancel_all(self) -> None:
        for task in list(self._tasks.values()):
            task.worker.request_cancel()

    def keys(self) -> List[str]:
        return list(self._tasks)


def format_worker_error(prefix: str, error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP 错误: {error.code} {error.reason}"
    if isinstance(error, urllib.error.URLError):
        return f"网络错误: {error.reason}"
    return f"{prefix}: {error}"


class DirectoryLoadWorker(CancellableWorker):
    finished = Signal(list)
    cancelled = Signal()
    error = Signal(str)
    progress = Signal(int)

    def __init__(self, client: SeaweedClient, base_url: str, dir_path: str, page_limit: int):
        super().__init__()
        self.client = client
        self.base_url = base_url
        self.dir_path = dir_path
        self.page_limit = page_limit

    def run(self) -> None:
        try:
            entries = self.client.list_dir(
                self.base_url,
                self.dir_path,
                self.page_limit,
                on_progress=self.progress.emit,
                cancel_check=self.is_cancelled,
            )
            self.finished.emit(entries)
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(format_worker_error("加载异常", e))


class PreviewLoadWorker(CancellableWorker):
    finished = Signal(dict)
    cancelled = Signal()
    error = Signal(str)

    def __init__(
        self,
        client: SeaweedClient,
        preview_type: str,
        base_url: str,
        full_path: str,
    ):
        super().__init__()
        self.client = client
        self.preview_type = preview_type
        self.base_url = base_url
        self.full_path = full_path

    def run(self) -> None:
        owned_temp_dir = ""
        try:
            self.token.raise_if_cancelled()
            result: Dict[str, Any] = {
                "preview_type": self.preview_type,
                "base_url": self.base_url,
                "full_path": self.full_path,
            }
            if self.preview_type == "text":
                result["content"] = self.client.preview_file(
                    self.base_url,
                    self.full_path,
                    cancel_check=self.is_cancelled,
                )
            elif self.preview_type == "image":
                owned_temp_dir = tempfile.mkdtemp(prefix=f"{APP_NAME}-image-")
                local_path = safe_local_path(owned_temp_dir, basename(self.full_path))
                self.client.download_file_to_local(
                    self.base_url,
                    self.full_path,
                    local_path,
                    cancel_check=self.is_cancelled,
                )
                result["temp_dir"] = owned_temp_dir
                result["local_path"] = local_path
            elif self.preview_type == "model":
                extension = get_path_extension(self.full_path).lstrip(".") or "model"
                owned_temp_dir = tempfile.mkdtemp(prefix=f"{APP_NAME}-{extension}-")
                local_path = self.prepare_model(owned_temp_dir)
                result["temp_dir"] = owned_temp_dir
                result["local_path"] = local_path
            else:
                raise RuntimeError(f"不支持的预览类型: {self.preview_type}")
            self.token.raise_if_cancelled()
            self.finished.emit(result)
            owned_temp_dir = ""
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(format_worker_error("预览准备失败", e))
        finally:
            if owned_temp_dir:
                shutil.rmtree(owned_temp_dir, ignore_errors=True)

    def prepare_model(self, temp_dir: str) -> str:
        original_local_path = safe_local_path(temp_dir, basename(self.full_path))
        self.client.download_file_to_local(
            self.base_url,
            self.full_path,
            original_local_path,
            cancel_check=self.is_cancelled,
        )
        self.token.raise_if_cancelled()

        detected_format = sniff_model_format(original_local_path)
        local_model_path = original_local_path
        if detected_format == "glb" and get_path_extension(original_local_path) != ".glb":
            local_model_path = replace_extension(original_local_path, ".glb")
            os.replace(original_local_path, local_model_path)
        elif detected_format == "gltf":
            if get_path_extension(original_local_path) != ".gltf":
                local_model_path = replace_extension(original_local_path, ".gltf")
                os.replace(original_local_path, local_model_path)
            self.download_gltf_sidecar_resources(temp_dir, local_model_path)
        return local_model_path

    def download_gltf_sidecar_resources(self, temp_dir: str, local_model_path: str) -> None:
        remote_dir = posixpath.dirname(normalize_dir_path(self.full_path))
        for resource_path in collect_gltf_resource_paths(local_model_path):
            self.token.raise_if_cancelled()
            remote_resource_path = normalize_dir_path(posixpath.join(remote_dir, resource_path))
            local_resource_path = safe_local_path(temp_dir, resource_path)
            self.client.download_file_to_local(
                self.base_url,
                remote_resource_path,
                local_resource_path,
                cancel_check=self.is_cancelled,
            )


class FileDownloadWorker(CancellableWorker):
    progress = Signal(int, int)
    finished = Signal(str)
    cancelled = Signal()
    error = Signal(str)

    def __init__(
        self,
        client: SeaweedClient,
        base_url: str,
        full_path: str,
        local_path: str,
    ):
        super().__init__()
        self.client = client
        self.base_url = base_url
        self.full_path = full_path
        self.local_path = local_path

    def run(self) -> None:
        try:
            last_progress_emit = 0.0

            def emit_progress(downloaded: int, total: int) -> None:
                nonlocal last_progress_emit
                now = time.monotonic()
                if downloaded >= total > 0 or now - last_progress_emit >= 0.1:
                    last_progress_emit = now
                    self.progress.emit(downloaded, total)

            self.client.download_file_to_local(
                self.base_url,
                self.full_path,
                self.local_path,
                cancel_check=self.is_cancelled,
                on_progress=emit_progress,
            )
            self.finished.emit(self.local_path)
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(format_worker_error("保存失败", e))


class SaveDirectoryWorker(CancellableWorker):
    progress = Signal(str, int, int, int, str)
    finished = Signal(dict)
    cancelled = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        client: SeaweedClient,
        base_url: str,
        source_dir: str,
        target_dir: str,
        page_limit: int,
    ):
        super().__init__()
        self.client = client
        self.base_url = base_url
        self.source_dir = normalize_dir_path(source_dir)
        self.target_dir = os.path.abspath(target_dir)
        self.page_limit = page_limit

    def run(self) -> None:
        try:
            files = self.collect_files()
            total_files = len(files)
            downloaded = 0
            source_prefix = self.source_dir.rstrip("/") or "/"
            for full_path in files:
                self.token.raise_if_cancelled()
                rel_path = self.make_relative_path(full_path, source_prefix)
                local_path = safe_local_path(self.target_dir, rel_path)
                self.client.download_file_to_local(
                    self.base_url,
                    full_path,
                    local_path,
                    cancel_check=self.is_cancelled,
                )
                downloaded += 1
                self.progress.emit("download", 0, total_files, downloaded, full_path)
            self.finished.emit(
                {
                    "total_files": total_files,
                    "downloaded_files": downloaded,
                    "target_dir": self.target_dir,
                }
            )
        except OperationCancelled:
            self.cancelled.emit("用户已中断保存任务")
        except Exception as e:
            self.error.emit(format_worker_error("保存失败", e))

    def collect_files(self) -> List[str]:
        queue = deque([self.source_dir])
        queued_dirs = {self.source_dir}
        files: List[str] = []
        scanned_dirs = 0
        while queue:
            self.token.raise_if_cancelled()
            current = queue.popleft()
            entries = self.client.list_dir(
                self.base_url,
                current,
                self.page_limit,
                cancel_check=self.is_cancelled,
            )
            scanned_dirs += 1
            for entry in entries:
                raw_path = str(entry.get("FullPath", "")).strip()
                if not raw_path:
                    continue
                full_path = normalize_dir_path(raw_path)
                self.make_relative_path(full_path, self.source_dir)
                if is_directory(entry):
                    if full_path not in queued_dirs:
                        queued_dirs.add(full_path)
                        queue.append(full_path)
                else:
                    files.append(full_path)
            self.progress.emit("scan", scanned_dirs, len(files), 0, current)
        return files

    @staticmethod
    def make_relative_path(full_path: str, source_prefix: str) -> str:
        normalized = normalize_dir_path(full_path)
        prefix = source_prefix.rstrip("/")
        if not prefix:
            relative = normalized.lstrip("/")
            return relative or basename(normalized)
        if prefix and normalized.startswith(prefix + "/"):
            return normalized[len(prefix) + 1 :]
        if normalized == prefix:
            return basename(normalized)
        raise ValueError(f"服务端返回了源目录之外的路径: {full_path}")
