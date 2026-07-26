import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional

from .core import (
    DOWNLOAD_CHUNK_SIZE,
    MAX_PAGES,
    PAGE_LIMIT,
    PREVIEW_MAX_BYTES,
    basename,
    join_url,
    sanitize_positive_int,
)


CancelCheck = Optional[Callable[[], bool]]
ProgressCallback = Optional[Callable[[int, int], None]]


class OperationCancelled(RuntimeError):
    pass


def ensure_not_cancelled(cancel_check: CancelCheck) -> None:
    if cancel_check is not None and cancel_check():
        raise OperationCancelled("操作已取消")


def http_get_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    cancel_check: CancelCheck = None,
) -> Dict[str, Any]:
    ensure_not_cancelled(cancel_check)
    if params:
        query = urllib.parse.urlencode(params)
        final_url = f"{url}?{query}"
    else:
        final_url = url
    req = urllib.request.Request(final_url, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    ensure_not_cancelled(cancel_check)
    return json.loads(raw.decode("utf-8"))


def http_get_bytes(
    url: str,
    cancel_check: CancelCheck = None,
) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        chunks: List[bytes] = []
        remaining = PREVIEW_MAX_BYTES
        while remaining > 0:
            ensure_not_cancelled(cancel_check)
            chunk = resp.read(min(DOWNLOAD_CHUNK_SIZE, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    ensure_not_cancelled(cancel_check)
    return b"".join(chunks)


class SeaweedClient:
    def list_dir(
        self,
        base_url: str,
        dir_path: str,
        page_limit: int,
        on_progress: Optional[Callable[[int], None]] = None,
        cancel_check: CancelCheck = None,
    ) -> List[Dict[str, Any]]:
        url = join_url(base_url, dir_path)
        all_entries: List[Dict[str, Any]] = []
        last_file_name = ""
        seen_cursors = set()
        page_count = 0
        effective_page_limit = sanitize_positive_int(page_limit, PAGE_LIMIT)
        while True:
            ensure_not_cancelled(cancel_check)
            page_count += 1
            if page_count > MAX_PAGES:
                raise RuntimeError("分页次数过多，已中断加载（可能是分页游标无效）")
            payload = http_get_json(
                url,
                params={"limit": effective_page_limit, "lastFileName": last_file_name},
                cancel_check=cancel_check,
            )
            entries = payload.get("Entries") or []
            if not entries:
                break
            all_entries.extend(entries)
            if on_progress is not None:
                on_progress(len(all_entries))
            payload_cursor = payload.get("LastFileName")
            if isinstance(payload_cursor, str) and payload_cursor.strip():
                next_cursor = payload_cursor.strip()
            else:
                next_cursor = basename(str(entries[-1].get("FullPath", "")))
            if next_cursor == last_file_name or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            last_file_name = next_cursor
            if payload.get("ShouldDisplayLoadMore") is False:
                break
            if len(entries) < effective_page_limit:
                break
        ensure_not_cancelled(cancel_check)
        return all_entries

    def preview_file(
        self,
        base_url: str,
        full_path: str,
        cancel_check: CancelCheck = None,
    ) -> str:
        data = http_get_bytes(join_url(base_url, full_path), cancel_check=cancel_check)
        return data.decode("utf-8", errors="replace")

    def download_file_to_local(
        self,
        base_url: str,
        full_path: str,
        local_file_path: str,
        cancel_check: CancelCheck = None,
        on_progress: ProgressCallback = None,
        atomic: bool = True,
    ) -> None:
        url = join_url(base_url, full_path)
        req = urllib.request.Request(url, method="GET")
        parent_dir = os.path.dirname(local_file_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        temp_path = local_file_path
        if atomic:
            temp_path = f"{local_file_path}.part-{uuid.uuid4().hex}"
        downloaded = 0
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                total_header = resp.headers.get("Content-Length", "")
                try:
                    total = max(0, int(total_header))
                except (TypeError, ValueError):
                    total = 0
                with open(temp_path, "wb") as f:
                    while True:
                        ensure_not_cancelled(cancel_check)
                        chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress is not None:
                            on_progress(downloaded, total)
                    f.flush()
                    os.fsync(f.fileno())
            ensure_not_cancelled(cancel_check)
            if atomic:
                os.replace(temp_path, local_file_path)
        except Exception:
            if atomic:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise
