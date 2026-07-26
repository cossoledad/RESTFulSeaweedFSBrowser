import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional

from .client import OperationCancelled, SeaweedClient, ensure_not_cancelled
from .i18n import tr


CancelCheck = Optional[Callable[[], bool]]
ProgressCallback = Optional[Callable[[int, int, str], None]]


@dataclass(frozen=True)
class DownloadItem:
    remote_path: str
    local_path: str


def download_files_concurrently(
    client: SeaweedClient,
    base_url: str,
    items: Iterable[DownloadItem],
    max_workers: int,
    cancel_check: CancelCheck = None,
    on_progress: ProgressCallback = None,
) -> int:
    """Download files with a bounded number of workers and in-flight futures."""

    if max_workers <= 0:
        raise ValueError(tr("max_workers 必须大于 0"))

    item_list = list(items)
    total = len(item_list)
    if not item_list:
        return 0

    stop_event = threading.Event()

    def should_cancel() -> bool:
        return stop_event.is_set() or bool(cancel_check and cancel_check())

    def download(item: DownloadItem) -> str:
        client.download_file_to_local(
            base_url,
            item.remote_path,
            item.local_path,
            cancel_check=should_cancel,
        )
        return item.remote_path

    worker_count = min(max_workers, total)
    executor = ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="seaweed-download",
    )
    pending: Dict[Future[str], DownloadItem] = {}
    next_index = 0
    completed = 0

    def submit_next() -> bool:
        nonlocal next_index
        if next_index >= total:
            return False
        item = item_list[next_index]
        next_index += 1
        pending[executor.submit(download, item)] = item
        return True

    try:
        for _ in range(worker_count):
            submit_next()

        while pending:
            ensure_not_cancelled(cancel_check)
            done, _ = wait(
                tuple(pending),
                timeout=0.1,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                continue
            completed_paths = []
            failures = []
            for future in done:
                pending.pop(future)
                try:
                    completed_paths.append(future.result())
                except Exception as error:
                    failures.append(error)
            if failures:
                primary_error = next(
                    (
                        error
                        for error in failures
                        if not isinstance(error, OperationCancelled)
                    ),
                    failures[0],
                )
                raise primary_error
            for remote_path in completed_paths:
                completed += 1
                if on_progress is not None:
                    on_progress(completed, total, remote_path)
                submit_next()
        return completed
    except Exception:
        stop_event.set()
        for future in pending:
            future.cancel()
        raise
    finally:
        stop_event.set()
        executor.shutdown(wait=True, cancel_futures=True)
