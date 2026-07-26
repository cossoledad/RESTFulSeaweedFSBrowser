import os
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from .client import OperationCancelled, SeaweedClient, ensure_not_cancelled


CancelCheck = Optional[Callable[[], bool]]
ProgressCallback = Optional[Callable[[int, int, int, int, str], None]]


@dataclass(frozen=True)
class UploadItem:
    local_path: str
    remote_path: str
    size: int


@dataclass(frozen=True)
class UploadFailure:
    item: UploadItem
    error: str


@dataclass(frozen=True)
class UploadBatchResult:
    total_files: int
    uploaded_files: int
    uploaded_bytes: int
    total_bytes: int
    failures: List[UploadFailure]


def build_upload_items(
    local_paths: Iterable[str],
    remote_directory: str,
    join_child: Callable[[str, str], str],
) -> List[UploadItem]:
    items: List[UploadItem] = []
    seen_targets = set()
    for local_path in local_paths:
        absolute_path = os.path.abspath(local_path)
        if not os.path.isfile(absolute_path):
            raise ValueError(f"不是普通文件: {local_path}")
        remote_path = join_child(remote_directory, os.path.basename(absolute_path))
        if remote_path in seen_targets:
            raise ValueError(f"上传列表包含重复目标名称: {os.path.basename(absolute_path)}")
        seen_targets.add(remote_path)
        items.append(
            UploadItem(
                local_path=absolute_path,
                remote_path=remote_path,
                size=os.path.getsize(absolute_path),
            )
        )
    return items


def upload_files_concurrently(
    client: SeaweedClient,
    base_url: str,
    items: Iterable[UploadItem],
    max_workers: int,
    cancel_check: CancelCheck = None,
    on_progress: ProgressCallback = None,
) -> UploadBatchResult:
    if max_workers <= 0:
        raise ValueError("max_workers 必须大于 0")

    item_list = list(items)
    total_files = len(item_list)
    total_bytes = sum(item.size for item in item_list)
    if not item_list:
        return UploadBatchResult(0, 0, 0, 0, [])

    stop_event = threading.Event()
    progress_lock = threading.Lock()
    item_progress: Dict[str, int] = {item.remote_path: 0 for item in item_list}

    def should_cancel() -> bool:
        return stop_event.is_set() or bool(cancel_check and cancel_check())

    def upload(item: UploadItem) -> UploadItem:
        def update_progress(uploaded: int, _: int) -> None:
            with progress_lock:
                item_progress[item.remote_path] = uploaded
                current_total = sum(item_progress.values())
            if on_progress is not None:
                on_progress(current_total, total_bytes, completed, total_files, item.remote_path)

        client.upload_file(
            base_url,
            item.remote_path,
            item.local_path,
            cancel_check=should_cancel,
            on_progress=update_progress,
        )
        return item

    worker_count = min(max_workers, total_files)
    executor = ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="seaweed-upload",
    )
    pending: Dict[Future[UploadItem], UploadItem] = {}
    next_index = 0
    completed = 0
    uploaded_files = 0
    failures: List[UploadFailure] = []

    def submit_next() -> bool:
        nonlocal next_index
        if next_index >= total_files:
            return False
        item = item_list[next_index]
        next_index += 1
        pending[executor.submit(upload, item)] = item
        return True

    try:
        for _ in range(worker_count):
            submit_next()
        while pending:
            ensure_not_cancelled(cancel_check)
            done, _ = wait(tuple(pending), timeout=0.1, return_when=FIRST_COMPLETED)
            if not done:
                continue
            for future in done:
                item = pending.pop(future)
                try:
                    future.result()
                    uploaded_files += 1
                    with progress_lock:
                        item_progress[item.remote_path] = item.size
                except OperationCancelled:
                    raise
                except Exception as error:
                    failures.append(UploadFailure(item=item, error=str(error)))
                completed += 1
                if on_progress is not None:
                    with progress_lock:
                        current_total = sum(item_progress.values())
                    on_progress(
                        current_total,
                        total_bytes,
                        completed,
                        total_files,
                        item.remote_path,
                    )
                submit_next()
        return UploadBatchResult(
            total_files=total_files,
            uploaded_files=uploaded_files,
            uploaded_bytes=sum(item_progress.values()),
            total_bytes=total_bytes,
            failures=failures,
        )
    except Exception:
        stop_event.set()
        for future in pending:
            future.cancel()
        raise
    finally:
        stop_event.set()
        executor.shutdown(wait=True, cancel_futures=True)
