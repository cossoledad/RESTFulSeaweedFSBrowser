import json
import os
import posixpath
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .i18n import DEFAULT_LANGUAGE, normalize_language, tr


APP_NAME = "SeaweedFSBrowser"
APP_VERSION = "1.1.1"
DEFAULT_BASE_URL = "file:///C:/"
DEFAULT_ROOT_DIR = "/"
PAGE_LIMIT = 1000
PREVIEW_MAX_BYTES = 262144
GO_MODE_DIR_BIT = 0x80000000
MAX_PAGES = 10000
DOWNLOAD_CHUNK_SIZE = 65536
MAX_HISTORY = 100
DIRECTORY_CACHE_MAX_ENTRIES = 32
DIRECTORY_DOWNLOAD_WORKERS = 4
UPLOAD_WORKERS = 3
MAX_CONCURRENT_PREVIEW_LOADS = 3
MAX_CONCURRENT_FILE_SAVES = 3
DIRECTORY_CACHE_MAX_LIMIT = 256
DIRECTORY_DOWNLOAD_WORKERS_LIMIT = 16
UPLOAD_WORKERS_LIMIT = 16
CONCURRENT_TASK_LIMIT = 16
SUPPORTED_MODEL_EXTENSIONS = {".glb", ".gltf"}
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def sanitize_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def sanitize_bounded_int(value: Any, default: int, maximum: int) -> int:
    return min(sanitize_positive_int(value, default), maximum)


def get_config_path() -> str:
    appdata = os.getenv("APPDATA")
    if not appdata:
        appdata = os.path.join(os.path.expanduser("~"), ".config")
    config_dir = os.path.join(appdata, APP_NAME)
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")


@dataclass
class AppConfig:
    language: str = DEFAULT_LANGUAGE
    base_url: str = DEFAULT_BASE_URL
    root_dir: str = DEFAULT_ROOT_DIR
    page_limit: int = PAGE_LIMIT
    directory_cache_max_entries: int = DIRECTORY_CACHE_MAX_ENTRIES
    directory_download_workers: int = DIRECTORY_DOWNLOAD_WORKERS
    upload_workers: int = UPLOAD_WORKERS
    max_concurrent_preview_loads: int = MAX_CONCURRENT_PREVIEW_LOADS
    max_concurrent_file_saves: int = MAX_CONCURRENT_FILE_SAVES
    location_history: List[Dict[str, str]] = field(default_factory=list)
    search_history: List[str] = field(default_factory=list)


def load_config() -> AppConfig:
    path = get_config_path()
    if not os.path.exists(path):
        return AppConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        location_hist_raw = raw.get("location_history")
        search_hist_raw = raw.get("search_history", [])
        # The previous schema kept the address and root histories independently.
        # Those combinations were ambiguous, so deliberately start from the safe
        # local default instead of attempting to reconstruct them.
        if not isinstance(location_hist_raw, list):
            return AppConfig(
                language=normalize_language(raw.get("language", DEFAULT_LANGUAGE)),
                search_history=[str(x) for x in search_hist_raw if isinstance(x, str)],
            )
        return AppConfig(
            language=normalize_language(raw.get("language", DEFAULT_LANGUAGE)),
            base_url=normalize_base_url(str(raw.get("base_url", DEFAULT_BASE_URL))),
            root_dir=normalize_dir_path(str(raw.get("root_dir", DEFAULT_ROOT_DIR))),
            page_limit=sanitize_positive_int(raw.get("page_limit", PAGE_LIMIT), PAGE_LIMIT),
            directory_cache_max_entries=sanitize_bounded_int(
                raw.get("directory_cache_max_entries", DIRECTORY_CACHE_MAX_ENTRIES),
                DIRECTORY_CACHE_MAX_ENTRIES,
                DIRECTORY_CACHE_MAX_LIMIT,
            ),
            directory_download_workers=sanitize_bounded_int(
                raw.get("directory_download_workers", DIRECTORY_DOWNLOAD_WORKERS),
                DIRECTORY_DOWNLOAD_WORKERS,
                DIRECTORY_DOWNLOAD_WORKERS_LIMIT,
            ),
            upload_workers=sanitize_bounded_int(
                raw.get("upload_workers", UPLOAD_WORKERS),
                UPLOAD_WORKERS,
                UPLOAD_WORKERS_LIMIT,
            ),
            max_concurrent_preview_loads=sanitize_bounded_int(
                raw.get(
                    "max_concurrent_preview_loads",
                    MAX_CONCURRENT_PREVIEW_LOADS,
                ),
                MAX_CONCURRENT_PREVIEW_LOADS,
                CONCURRENT_TASK_LIMIT,
            ),
            max_concurrent_file_saves=sanitize_bounded_int(
                raw.get("max_concurrent_file_saves", MAX_CONCURRENT_FILE_SAVES),
                MAX_CONCURRENT_FILE_SAVES,
                CONCURRENT_TASK_LIMIT,
            ),
            location_history=normalize_location_history(location_hist_raw),
            search_history=[str(x) for x in search_hist_raw if isinstance(x, str)],
        )
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    path = get_config_path()
    data = {
        "language": normalize_language(cfg.language),
        "base_url": cfg.base_url,
        "root_dir": cfg.root_dir,
        "page_limit": sanitize_positive_int(cfg.page_limit, PAGE_LIMIT),
        "directory_cache_max_entries": sanitize_bounded_int(
            cfg.directory_cache_max_entries,
            DIRECTORY_CACHE_MAX_ENTRIES,
            DIRECTORY_CACHE_MAX_LIMIT,
        ),
        "directory_download_workers": sanitize_bounded_int(
            cfg.directory_download_workers,
            DIRECTORY_DOWNLOAD_WORKERS,
            DIRECTORY_DOWNLOAD_WORKERS_LIMIT,
        ),
        "upload_workers": sanitize_bounded_int(
            cfg.upload_workers,
            UPLOAD_WORKERS,
            UPLOAD_WORKERS_LIMIT,
        ),
        "max_concurrent_preview_loads": sanitize_bounded_int(
            cfg.max_concurrent_preview_loads,
            MAX_CONCURRENT_PREVIEW_LOADS,
            CONCURRENT_TASK_LIMIT,
        ),
        "max_concurrent_file_saves": sanitize_bounded_int(
            cfg.max_concurrent_file_saves,
            MAX_CONCURRENT_FILE_SAVES,
            CONCURRENT_TASK_LIMIT,
        ),
        "location_history": normalize_location_history(cfg.location_history),
        "search_history": cfg.search_history[:MAX_HISTORY],
    }
    parent = os.path.dirname(path)
    fd, temp_path = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def update_history(history: List[str], value: str) -> List[str]:
    stripped = value.strip()
    if not stripped:
        return history[:MAX_HISTORY]
    return ([stripped] + [item for item in history if item != stripped])[:MAX_HISTORY]


def normalize_location_history(value: Any) -> List[Dict[str, str]]:
    """Return valid, de-duplicated address/root pairs from the current schema."""
    if not isinstance(value, list):
        return []
    result: List[Dict[str, str]] = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        base_url = normalize_base_url(str(item.get("base_url", "")))
        root_dir = normalize_dir_path(str(item.get("root_dir", "")))
        if not base_url or (base_url, root_dir) in seen:
            continue
        seen.add((base_url, root_dir))
        result.append({"base_url": base_url, "root_dir": root_dir})
        if len(result) >= MAX_HISTORY:
            break
    return result


def update_location_history(
    history: List[Dict[str, str]], base_url: str, root_dir: str
) -> List[Dict[str, str]]:
    entry = {
        "base_url": normalize_base_url(base_url),
        "root_dir": normalize_dir_path(root_dir),
    }
    if not entry["base_url"]:
        return normalize_location_history(history)
    return [entry] + [
        item
        for item in normalize_location_history(history)
        if (item["base_url"], item["root_dir"])
        != (entry["base_url"], entry["root_dir"])
    ][: MAX_HISTORY - 1]


def normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def normalize_dir_path(path: str) -> str:
    if not path:
        return "/"
    cleaned = path.strip()
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return cleaned


def join_url(base_url: str, full_path: str) -> str:
    normalized_path = normalize_dir_path(full_path)
    encoded_path = urllib.parse.quote(
        normalized_path,
        safe="/:@-._~!$&'()*+,;=",
    )
    return normalize_base_url(base_url) + encoded_path


def basename(path: str) -> str:
    stripped = path.rstrip("/")
    if not stripped:
        return "/"
    name = stripped.split("/")[-1]
    return name or "/"


def validate_remote_child_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError(tr("名称不能为空"))
    if value in {".", ".."}:
        raise ValueError(tr("名称不能为 . 或 .."))
    if "/" in value or "\\" in value:
        raise ValueError(tr("名称不能包含路径分隔符"))
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(tr("名称不能包含控制字符"))
    return value


def join_remote_child(directory: str, name: str) -> str:
    child_name = validate_remote_child_name(name)
    parent = normalize_dir_path(directory).rstrip("/")
    if not parent:
        return f"/{child_name}"
    return f"{parent}/{child_name}"


def remote_path_is_within_root(path: str, root_dir: str) -> bool:
    candidate = posixpath.normpath(normalize_dir_path(path))
    root = posixpath.normpath(normalize_dir_path(root_dir))
    if root == "/":
        return candidate.startswith("/")
    return candidate == root or candidate.startswith(root.rstrip("/") + "/")


def get_path_extension(path: str) -> str:
    decoded_path = urllib.parse.unquote(path)
    _, ext = os.path.splitext(decoded_path)
    return ext.lower()


def replace_extension(path: str, new_extension: str) -> str:
    base, _ = os.path.splitext(path)
    return base + new_extension


def normalize_relative_path(path: str) -> str:
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if normalized in {"", "."}:
        raise ValueError(tr("相对路径为空"))
    if normalized.startswith("/") or normalized.startswith("../") or normalized == "..":
        raise ValueError(tr("路径越界: {path}", path=path))
    return normalized


def safe_local_path(root_dir: str, relative_path: str) -> str:
    normalized = normalize_relative_path(relative_path)
    root = os.path.realpath(root_dir)
    target = os.path.realpath(os.path.join(root, *normalized.split("/")))
    try:
        common = os.path.commonpath([root, target])
    except ValueError as e:
        raise ValueError(tr("路径越界: {path}", path=relative_path)) from e
    if os.path.normcase(common) != os.path.normcase(root):
        raise ValueError(tr("路径越界: {path}", path=relative_path))
    return target


def format_time(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            if text.endswith("Z"):
                dt = datetime.fromisoformat(text[:-1]).replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return text
    try:
        timestamp = int(value)
        if timestamp > 10**12:
            timestamp //= 10**9
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def parse_time_sort_value(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        try:
            if text.endswith("Z"):
                dt = datetime.fromisoformat(text[:-1]).replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return sanitize_positive_int(text, 0)
    timestamp = sanitize_positive_int(value, 0)
    if timestamp > 10**12:
        timestamp //= 10**9
    return timestamp


def format_size(size: Any) -> str:
    if size is None or size == "":
        return ""
    try:
        value = float(int(size))
    except Exception:
        return str(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return str(size)


def parse_mode_value(mode: Any) -> Optional[int]:
    if isinstance(mode, int):
        return mode
    if isinstance(mode, str):
        value = mode.strip()
        if not value:
            return None
        try:
            return int(value, 0)
        except ValueError:
            if value.isdigit():
                return int(value)
    return None


def is_directory(entry: dict) -> bool:
    mode = parse_mode_value(entry.get("Mode"))
    if mode is not None and (mode & GO_MODE_DIR_BIT or mode & 0o040000):
        return True
    for key in ("IsDirectory", "isDirectory", "is_dir", "dir"):
        if entry.get(key) is True:
            return True
    if str(entry.get("Mime", "")) == "inode/directory":
        return True
    return str(entry.get("FullPath", "")).endswith("/")
