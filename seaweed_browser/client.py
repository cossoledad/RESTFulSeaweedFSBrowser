import base64
import hashlib
import http.client
import json
import mimetypes
import os
import shutil
import ssl
import stat
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
    normalize_dir_path,
    sanitize_positive_int,
)
from .i18n import tr


CancelCheck = Optional[Callable[[], bool]]
ProgressCallback = Optional[Callable[[int, int], None]]


class OperationCancelled(RuntimeError):
    pass


class SeaweedHttpError(RuntimeError):
    def __init__(self, status: int, reason: str, detail: str = ""):
        self.status = status
        self.reason = reason
        self.detail = detail
        message = f"HTTP {status} {reason}".strip()
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


def ensure_not_cancelled(cancel_check: CancelCheck) -> None:
    if cancel_check is not None and cancel_check():
        raise OperationCancelled(tr("操作已取消"))


def is_local_filesystem_url(base_url: str) -> bool:
    return urllib.parse.urlsplit(base_url.strip()).scheme.lower() == "file"


def local_filesystem_path(base_url: str, remote_path: str) -> str:
    """Map a virtual POSIX path under a file URL to a contained local path."""
    parsed = urllib.parse.urlsplit(base_url.strip())
    if parsed.scheme.lower() != "file" or parsed.netloc not in {"", "localhost"}:
        raise ValueError(tr("不支持的本地文件系统地址: {url}", url=base_url))
    base_path = urllib.request.url2pathname(urllib.parse.unquote(parsed.path))
    if os.name == "nt":
        base_path = base_path.lstrip("/")
        if len(base_path) == 2 and base_path[1] == ":":
            base_path += os.sep
    root = os.path.realpath(os.path.abspath(base_path))
    relative = normalize_dir_path(remote_path).lstrip("/")
    target = os.path.realpath(os.path.join(root, *relative.split("/"))) if relative else root
    try:
        if os.path.commonpath([root, target]) != root:
            raise ValueError(tr("路径越界: {path}", path=remote_path))
    except ValueError as error:
        raise ValueError(tr("路径越界: {path}", path=remote_path)) from error
    return target


def local_entry(dir_path: str, item: os.DirEntry[str]) -> Dict[str, Any]:
    metadata = item.stat(follow_symlinks=False)
    full_path = normalize_dir_path(dir_path).rstrip("/") + "/" + item.name
    if not full_path.startswith("/"):
        full_path = "/" + full_path
    is_dir = stat.S_ISDIR(metadata.st_mode)
    return {
        "FullPath": full_path,
        "Mode": metadata.st_mode,
        "FileSize": 0 if is_dir else metadata.st_size,
        "Mtime": int(metadata.st_mtime),
        "Crtime": int(metadata.st_ctime),
        "Mime": "inode/directory" if is_dir else (mimetypes.guess_type(item.name)[0] or ""),
        "IsDirectory": is_dir,
    }


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


def open_http_connection(
    url: str,
    timeout: int,
) -> tuple[http.client.HTTPConnection, str]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(tr("不支持的服务地址: {url}", url=url))
    port = parsed.port
    if parsed.scheme == "https":
        connection: http.client.HTTPConnection = http.client.HTTPSConnection(
            parsed.hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    else:
        connection = http.client.HTTPConnection(
            parsed.hostname,
            port=port,
            timeout=timeout,
        )
    request_target = parsed.path or "/"
    if parsed.query:
        request_target = f"{request_target}?{parsed.query}"
    return connection, request_target


def read_json_response(response: http.client.HTTPResponse) -> Dict[str, Any]:
    raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        return {"raw": tr("服务器响应内容过大")}
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": raw.decode("utf-8", errors="replace")}
    return payload if isinstance(payload, dict) else {"result": payload}


def raise_for_response(
    response: http.client.HTTPResponse,
    payload: Dict[str, Any],
) -> None:
    if 200 <= response.status < 300:
        return
    detail = str(payload.get("error") or payload.get("Error") or payload.get("raw") or "")
    raise SeaweedHttpError(response.status, response.reason or "", detail)


class SeaweedClient:
    def create_directory(
        self,
        base_url: str,
        full_path: str,
        cancel_check: CancelCheck = None,
    ) -> Dict[str, Any]:
        ensure_not_cancelled(cancel_check)
        if is_local_filesystem_url(base_url):
            target = local_filesystem_path(base_url, full_path)
            os.mkdir(target)
            ensure_not_cancelled(cancel_check)
            return {"FullPath": normalize_dir_path(full_path), "name": basename(full_path)}
        url = join_url(base_url, full_path).rstrip("/") + "/"
        connection, request_target = open_http_connection(url, timeout=30)
        try:
            connection.putrequest("POST", request_target)
            connection.putheader("Accept", "application/json")
            connection.putheader("Content-Length", "0")
            connection.endheaders()
            ensure_not_cancelled(cancel_check)
            response = connection.getresponse()
            payload = read_json_response(response)
            raise_for_response(response, payload)
            ensure_not_cancelled(cancel_check)
            return payload
        finally:
            connection.close()

    def upload_file(
        self,
        base_url: str,
        full_path: str,
        local_file_path: str,
        cancel_check: CancelCheck = None,
        on_progress: ProgressCallback = None,
    ) -> Dict[str, Any]:
        ensure_not_cancelled(cancel_check)
        stat_before = os.stat(local_file_path)
        if not os.path.isfile(local_file_path):
            raise ValueError(tr("不是普通文件: {path}", path=local_file_path))
        total = stat_before.st_size
        if is_local_filesystem_url(base_url):
            target = local_filesystem_path(base_url, full_path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            temp_path = f"{target}.part-{uuid.uuid4().hex}"
            copied = 0
            try:
                with open(local_file_path, "rb") as source, open(temp_path, "wb") as destination:
                    while True:
                        ensure_not_cancelled(cancel_check)
                        chunk = source.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        destination.write(chunk)
                        copied += len(chunk)
                        if on_progress is not None:
                            on_progress(copied, total)
                    destination.flush()
                    os.fsync(destination.fileno())
                ensure_not_cancelled(cancel_check)
                os.replace(temp_path, target)
            except Exception:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                raise
            return {"uploaded_bytes": copied, "verified": False}
        url = join_url(base_url, full_path)
        connection, request_target = open_http_connection(url, timeout=60)
        digest = hashlib.md5()
        uploaded = 0
        content_type = mimetypes.guess_type(local_file_path)[0] or "application/octet-stream"
        try:
            connection.putrequest("PUT", request_target)
            connection.putheader("Accept", "application/json")
            connection.putheader("Content-Type", content_type)
            connection.putheader("Content-Length", str(total))
            connection.endheaders()
            with open(local_file_path, "rb") as source:
                while uploaded < total:
                    ensure_not_cancelled(cancel_check)
                    chunk = source.read(min(DOWNLOAD_CHUNK_SIZE, total - uploaded))
                    if not chunk:
                        raise OSError(tr("本地文件在上传过程中被截断"))
                    connection.send(chunk)
                    digest.update(chunk)
                    uploaded += len(chunk)
                    if on_progress is not None:
                        on_progress(uploaded, total)
            ensure_not_cancelled(cancel_check)
            response = connection.getresponse()
            payload = read_json_response(response)
            raise_for_response(response, payload)
            ensure_not_cancelled(cancel_check)

            stat_after = os.stat(local_file_path)
            if (
                stat_after.st_size != stat_before.st_size
                or stat_after.st_mtime_ns != stat_before.st_mtime_ns
            ):
                raise RuntimeError(tr("本地文件在上传过程中发生变化，请重新上传"))

            local_md5 = base64.b64encode(digest.digest()).decode("ascii")
            remote_md5 = response.getheader("Content-MD5", "")
            if remote_md5 and remote_md5 != local_md5:
                raise RuntimeError(tr("上传已完成，但服务器返回的 MD5 校验值不一致"))
            payload["verified"] = bool(remote_md5)
            payload["uploaded_bytes"] = uploaded
            return payload
        finally:
            connection.close()

    def list_dir(
        self,
        base_url: str,
        dir_path: str,
        page_limit: int,
        on_progress: Optional[Callable[[int], None]] = None,
        cancel_check: CancelCheck = None,
    ) -> List[Dict[str, Any]]:
        if is_local_filesystem_url(base_url):
            target = local_filesystem_path(base_url, dir_path)
            entries: List[Dict[str, Any]] = []
            with os.scandir(target) as children:
                for child in children:
                    ensure_not_cancelled(cancel_check)
                    entries.append(local_entry(dir_path, child))
                    if on_progress is not None:
                        on_progress(len(entries))
            return entries
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
                raise RuntimeError(
                    tr("分页次数过多，已中断加载（可能是分页游标无效）")
                )
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
        if is_local_filesystem_url(base_url):
            target = local_filesystem_path(base_url, full_path)
            chunks: List[bytes] = []
            remaining = PREVIEW_MAX_BYTES
            with open(target, "rb") as source:
                while remaining > 0:
                    ensure_not_cancelled(cancel_check)
                    chunk = source.read(min(DOWNLOAD_CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace")
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
        if is_local_filesystem_url(base_url):
            source_path = local_filesystem_path(base_url, full_path)
            parent_dir = os.path.dirname(local_file_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            temp_path = f"{local_file_path}.part-{uuid.uuid4().hex}" if atomic else local_file_path
            copied = 0
            total = os.path.getsize(source_path)
            try:
                with open(source_path, "rb") as source, open(temp_path, "wb") as destination:
                    while True:
                        ensure_not_cancelled(cancel_check)
                        chunk = source.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        destination.write(chunk)
                        copied += len(chunk)
                        if on_progress is not None:
                            on_progress(copied, total)
                    destination.flush()
                    os.fsync(destination.fileno())
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
            return
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
