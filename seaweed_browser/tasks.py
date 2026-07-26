import os
import posixpath
import shutil
import tempfile
import threading
import time
import urllib.error
from collections import deque
from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal

from .cancellation import CancellationToken
from .client import OperationCancelled, SeaweedClient, SeaweedHttpError
from .core import (
    APP_NAME,
    DIRECTORY_DOWNLOAD_WORKERS,
    basename,
    get_path_extension,
    is_directory,
    normalize_dir_path,
    replace_extension,
    safe_local_path,
)
from .downloads import DownloadItem, download_files_concurrently
from .i18n import tr
from .model_files import collect_gltf_resource_paths, sniff_model_format
from .task_models import ProgressUnit, TaskError, TaskProgress
from .uploads import UploadItem, upload_files_concurrently


class CancellableWorker(QObject):
    progress_changed = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.token = CancellationToken()

    def request_cancel(self) -> None:
        self.token.cancel()

    def is_cancelled(self) -> bool:
        return self.token.is_cancelled()


def format_worker_error(prefix: str, error: Exception) -> str:
    if isinstance(error, SeaweedHttpError):
        messages = {
            403: tr("服务器拒绝写入，可能没有权限或受到 WORM 策略限制"),
            409: tr("目标名称与现有文件或目录冲突"),
            413: tr("服务器拒绝了文件大小"),
        }
        description = messages.get(error.status, str(error))
        if error.detail and error.detail not in description:
            description = f"{description}\n{error.detail}"
        return description
    if isinstance(error, urllib.error.HTTPError):
        return tr("HTTP 错误: {code} {reason}", code=error.code, reason=error.reason)
    if isinstance(error, urllib.error.URLError):
        return tr("网络错误: {reason}", reason=error.reason)
    return f"{prefix}: {error}"


class CreateDirectoryWorker(CancellableWorker):
    def __init__(
        self,
        client: SeaweedClient,
        base_url: str,
        parent_dir: str,
        target_path: str,
    ):
        super().__init__()
        self.client = client
        self.base_url = base_url
        self.parent_dir = parent_dir
        self.target_path = target_path

    def run(self) -> None:
        try:
            self.progress_changed.emit(
                TaskProgress.indeterminate(tr("创建文件夹"), self.target_path)
            )
            payload = self.client.create_directory(
                self.base_url,
                self.target_path,
                cancel_check=self.is_cancelled,
            )
            self.succeeded.emit(
                {
                    "base_url": self.base_url,
                    "parent_dir": self.parent_dir,
                    "target_path": self.target_path,
                    "response": payload,
                }
            )
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(
                TaskError(format_worker_error(tr("创建目录失败"), error))
            )


class UploadBatchWorker(CancellableWorker):
    def __init__(
        self,
        client: SeaweedClient,
        base_url: str,
        target_dir: str,
        items: List[UploadItem],
        max_workers: int,
    ):
        super().__init__()
        self.client = client
        self.base_url = base_url
        self.target_dir = target_dir
        self.items = list(items)
        self.max_workers = max_workers

    def run(self) -> None:
        try:
            last_progress_emit = 0.0
            progress_emit_lock = threading.Lock()

            def emit_progress(
                uploaded_bytes: int,
                total_bytes: int,
                completed_files: int,
                total_files: int,
                current_path: str,
            ) -> None:
                nonlocal last_progress_emit
                with progress_emit_lock:
                    now = time.monotonic()
                    if (
                        completed_files < total_files
                        and uploaded_bytes < total_bytes
                        and now - last_progress_emit < 0.1
                    ):
                        return
                    last_progress_emit = now
                if total_bytes > 0:
                    progress = TaskProgress.determinate(
                        uploaded_bytes,
                        total_bytes,
                        ProgressUnit.BYTES,
                        phase=tr("上传"),
                        detail=basename(current_path),
                        secondary_current=completed_files,
                        secondary_total=total_files,
                    )
                else:
                    progress = TaskProgress.determinate(
                        completed_files,
                        total_files,
                        ProgressUnit.ITEMS,
                        phase=tr("上传"),
                        detail=basename(current_path),
                    )
                self.progress_changed.emit(progress)

            result = upload_files_concurrently(
                self.client,
                self.base_url,
                self.items,
                self.max_workers,
                cancel_check=self.is_cancelled,
                on_progress=emit_progress,
            )
            payload = {
                "base_url": self.base_url,
                "target_dir": self.target_dir,
                "total_files": result.total_files,
                "uploaded_files": result.uploaded_files,
                "uploaded_bytes": result.uploaded_bytes,
                "total_bytes": result.total_bytes,
                "failures": [
                    {
                        "local_path": failure.item.local_path,
                        "remote_path": failure.item.remote_path,
                        "error": failure.error,
                    }
                    for failure in result.failures
                ],
            }
            if result.failures:
                self.failed.emit(
                    TaskError(
                        tr(
                            "部分文件上传失败：{failed}/{total}",
                            failed=len(result.failures),
                            total=result.total_files,
                        ),
                        retryable=True,
                        payload=payload,
                    )
                )
            else:
                self.succeeded.emit(payload)
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(TaskError(format_worker_error(tr("上传失败"), error)))


class DirectoryLoadWorker(CancellableWorker):
    def __init__(self, client: SeaweedClient, base_url: str, dir_path: str, page_limit: int):
        super().__init__()
        self.client = client
        self.base_url = base_url
        self.dir_path = dir_path
        self.page_limit = page_limit

    def run(self) -> None:
        try:
            def emit_progress(count: int) -> None:
                self.progress_changed.emit(
                    TaskProgress.indeterminate(
                        tr("加载目录"),
                        tr("已加载 {count} 条", count=count),
                    )
                )

            entries = self.client.list_dir(
                self.base_url,
                self.dir_path,
                self.page_limit,
                on_progress=emit_progress,
                cancel_check=self.is_cancelled,
            )
            self.succeeded.emit(entries)
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failed.emit(TaskError(format_worker_error(tr("加载异常"), e)))


class PreviewLoadWorker(CancellableWorker):
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
            self.progress_changed.emit(
                TaskProgress.indeterminate(
                    tr("准备预览"),
                    basename(self.full_path),
                )
            )
            result: Dict[str, Any] = {
                "preview_type": self.preview_type,
                "base_url": self.base_url,
                "full_path": self.full_path,
            }
            if self.preview_type == "text":
                self.progress_changed.emit(
                    TaskProgress.indeterminate(
                        tr("下载文本"),
                        basename(self.full_path),
                    )
                )
                result["content"] = self.client.preview_file(
                    self.base_url,
                    self.full_path,
                    cancel_check=self.is_cancelled,
                )
            elif self.preview_type == "image":
                self.progress_changed.emit(
                    TaskProgress.indeterminate(
                        tr("下载图片"),
                        basename(self.full_path),
                    )
                )
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
                self.progress_changed.emit(
                    TaskProgress.indeterminate(
                        tr("准备模型"),
                        basename(self.full_path),
                    )
                )
                extension = get_path_extension(self.full_path).lstrip(".") or "model"
                owned_temp_dir = tempfile.mkdtemp(prefix=f"{APP_NAME}-{extension}-")
                local_path = self.prepare_model(owned_temp_dir)
                result["temp_dir"] = owned_temp_dir
                result["local_path"] = local_path
            else:
                raise RuntimeError(
                    tr("不支持的预览类型: {type}", type=self.preview_type)
                )
            self.token.raise_if_cancelled()
            self.succeeded.emit(result)
            owned_temp_dir = ""
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failed.emit(
                TaskError(format_worker_error(tr("预览准备失败"), e))
            )
        finally:
            if owned_temp_dir:
                shutil.rmtree(owned_temp_dir, ignore_errors=True)

    def prepare_model(self, temp_dir: str) -> str:
        self.progress_changed.emit(
            TaskProgress.indeterminate(tr("下载模型"), basename(self.full_path))
        )
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
            self.progress_changed.emit(
                TaskProgress.indeterminate(
                    tr("分析 GLTF 资源"),
                    basename(self.full_path),
                )
            )
            self.download_gltf_sidecar_resources(temp_dir, local_model_path)
        return local_model_path

    def download_gltf_sidecar_resources(self, temp_dir: str, local_model_path: str) -> None:
        remote_dir = posixpath.dirname(normalize_dir_path(self.full_path))
        resource_paths = collect_gltf_resource_paths(local_model_path)
        for index, resource_path in enumerate(resource_paths, start=1):
            self.token.raise_if_cancelled()
            self.progress_changed.emit(
                TaskProgress.determinate(
                    index - 1,
                    len(resource_paths),
                    ProgressUnit.ITEMS,
                    phase=tr("下载 GLTF 资源"),
                    detail=resource_path,
                )
            )
            remote_resource_path = normalize_dir_path(posixpath.join(remote_dir, resource_path))
            local_resource_path = safe_local_path(temp_dir, resource_path)
            self.client.download_file_to_local(
                self.base_url,
                remote_resource_path,
                local_resource_path,
                cancel_check=self.is_cancelled,
            )


class FileDownloadWorker(CancellableWorker):
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
                    self.progress_changed.emit(
                        TaskProgress.determinate(
                            downloaded,
                            total,
                            ProgressUnit.BYTES,
                            phase=tr("下载"),
                            detail=basename(self.full_path),
                        )
                    )

            self.client.download_file_to_local(
                self.base_url,
                self.full_path,
                self.local_path,
                cancel_check=self.is_cancelled,
                on_progress=emit_progress,
            )
            self.succeeded.emit(self.local_path)
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failed.emit(TaskError(format_worker_error(tr("保存失败"), e)))


class SaveDirectoryWorker(CancellableWorker):
    def __init__(
        self,
        client: SeaweedClient,
        base_url: str,
        source_dir: str,
        target_dir: str,
        page_limit: int,
        max_download_workers: int = DIRECTORY_DOWNLOAD_WORKERS,
    ):
        super().__init__()
        self.client = client
        self.base_url = base_url
        self.source_dir = normalize_dir_path(source_dir)
        self.target_dir = os.path.abspath(target_dir)
        self.page_limit = page_limit
        self.max_download_workers = max_download_workers

    def run(self) -> None:
        try:
            files = self.collect_files()
            total_files = len(files)
            source_prefix = self.source_dir.rstrip("/") or "/"
            items = (
                DownloadItem(
                    remote_path=full_path,
                    local_path=safe_local_path(
                        self.target_dir,
                        self.make_relative_path(full_path, source_prefix),
                    ),
                )
                for full_path in files
            )
            downloaded = download_files_concurrently(
                self.client,
                self.base_url,
                items,
                max_workers=self.max_download_workers,
                cancel_check=self.is_cancelled,
                on_progress=lambda completed, total, current: self.progress_changed.emit(
                    TaskProgress.determinate(
                        completed,
                        total,
                        ProgressUnit.ITEMS,
                        phase=tr("下载目录"),
                        detail=basename(current),
                    )
                ),
            )
            self.succeeded.emit(
                {
                    "total_files": total_files,
                    "downloaded_files": downloaded,
                    "target_dir": self.target_dir,
                }
            )
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failed.emit(TaskError(format_worker_error(tr("保存失败"), e)))

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
            self.progress_changed.emit(
                TaskProgress.indeterminate(
                    tr("扫描目录"),
                    tr(
                        "已扫描 {dirs} 个目录，发现 {files} 个文件 · {current}",
                        dirs=scanned_dirs,
                        files=len(files),
                        current=current,
                    ),
                )
            )
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
        raise ValueError(
            tr(
                "服务端返回了源目录之外的路径: {path}",
                path=full_path,
            )
        )
