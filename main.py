import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# 减少 Windows 下字体探测产生的大量告警输出。
os.environ.setdefault("QT_LOGGING_RULES", "qt.text.font.db.warning=false;qt.qpa.fonts.warning=false")

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QAction, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "SeaweedFSBrowser"
DEFAULT_BASE_URL = "http://10.1.23.81:38888"
DEFAULT_ROOT_DIR = "/buckets/cax-dev/files/"
PAGE_LIMIT = 1000
PREVIEW_MAX_BYTES = 262144
GO_MODE_DIR_BIT = 0x80000000
MAX_PAGES = 10000
DOWNLOAD_CHUNK_SIZE = 65536
MAX_HISTORY = 100


def sanitize_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def get_config_path() -> str:
    appdata = os.getenv("APPDATA")
    if not appdata:
        appdata = os.path.join(os.path.expanduser("~"), ".config")
    config_dir = os.path.join(appdata, APP_NAME)
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(relative_path: str) -> str:
    return os.path.join(get_base_dir(), relative_path)


@dataclass
class AppConfig:
    base_url: str = DEFAULT_BASE_URL
    root_dir: str = DEFAULT_ROOT_DIR
    page_limit: int = PAGE_LIMIT
    base_url_history: List[str] = None
    root_dir_history: List[str] = None
    search_history: List[str] = None

    def __post_init__(self):
        if self.base_url_history is None:
            self.base_url_history = []
        if self.root_dir_history is None:
            self.root_dir_history = []
        if self.search_history is None:
            self.search_history = []


def load_config() -> AppConfig:
    path = get_config_path()
    if not os.path.exists(path):
        return AppConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        base_hist_raw = raw.get("base_url_history", [])
        root_hist_raw = raw.get("root_dir_history", [])
        search_hist_raw = raw.get("search_history", [])
        return AppConfig(
            base_url=str(raw.get("base_url", DEFAULT_BASE_URL)),
            root_dir=str(raw.get("root_dir", DEFAULT_ROOT_DIR)),
            page_limit=sanitize_positive_int(raw.get("page_limit", PAGE_LIMIT), PAGE_LIMIT),
            base_url_history=[str(x) for x in base_hist_raw if isinstance(x, str)],
            root_dir_history=[str(x) for x in root_hist_raw if isinstance(x, str)],
            search_history=[str(x) for x in search_hist_raw if isinstance(x, str)],
        )
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    path = get_config_path()
    data = {
        "base_url": cfg.base_url,
        "root_dir": cfg.root_dir,
        "page_limit": sanitize_positive_int(cfg.page_limit, PAGE_LIMIT),
        "base_url_history": cfg.base_url_history[:MAX_HISTORY],
        "root_dir_history": cfg.root_dir_history[:MAX_HISTORY],
        "search_history": cfg.search_history[:MAX_HISTORY],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_history(history: List[str], value: str) -> List[str]:
    v = value.strip()
    if not v:
        return history[:MAX_HISTORY]
    new_items = [v] + [x for x in history if x != v]
    return new_items[:MAX_HISTORY]


def open_path_in_file_explorer(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


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
    return normalize_base_url(base_url) + normalize_dir_path(full_path)


def basename(path: str) -> str:
    stripped = path.rstrip("/")
    if not stripped:
        return "/"
    name = stripped.split("/")[-1]
    return name or "/"


def format_time(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return ""
        try:
            # SeaweedFS 常见格式：2026-01-29T02:55:32Z
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return s
    try:
        ivalue = int(value)
        # 兼容纳秒时间戳
        if ivalue > 10**12:
            ivalue = ivalue // 10**9
        return datetime.fromtimestamp(ivalue).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def parse_time_sort_value(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return 0
        try:
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return sanitize_positive_int(s, 0)
    ivalue = sanitize_positive_int(value, 0)
    if ivalue > 10**12:
        ivalue = ivalue // 10**9
    return ivalue


def format_size(size: Any) -> str:
    if size is None or size == "":
        return ""
    try:
        n = int(size)
    except Exception:
        return str(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(n)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{n} B"


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


def is_directory(entry: Dict[str, Any]) -> bool:
    # SeaweedFS/Filer 的目录位通常来自 Go 的 os.FileMode (ModeDir = 1<<31)。
    mode = parse_mode_value(entry.get("Mode"))
    if mode is not None:
        if mode & GO_MODE_DIR_BIT:
            return True
        if mode & 0o040000:
            return True
    for key in ("IsDirectory", "isDirectory", "is_dir", "dir"):
        value = entry.get(key)
        if isinstance(value, bool) and value:
            return True
    mime = str(entry.get("Mime", ""))
    if mime == "inode/directory":
        return True
    full_path = str(entry.get("FullPath", ""))
    if full_path.endswith("/"):
        return True
    return False


class SortableTreeWidgetItem(QTreeWidgetItem):
    def __lt__(self, other: "QTreeWidgetItem") -> bool:
        tree = self.treeWidget()
        if tree is None:
            return super().__lt__(other)
        column = tree.sortColumn()
        left = self.data(column, Qt.ItemDataRole.UserRole + 1)
        right = other.data(column, Qt.ItemDataRole.UserRole + 1)
        if left is None or right is None:
            return super().__lt__(other)
        return left < right


def http_get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if params:
        query = urllib.parse.urlencode(params)
        final_url = f"{url}?{query}"
    else:
        final_url = url
    req = urllib.request.Request(final_url, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(PREVIEW_MAX_BYTES)


class SeaweedClient:
    def list_dir(
        self,
        base_url: str,
        dir_path: str,
        page_limit: int,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> List[Dict[str, Any]]:
        url = join_url(base_url, dir_path)
        all_entries: List[Dict[str, Any]] = []
        last_file_name = ""
        seen_cursors = set()
        page_count = 0
        effective_page_limit = sanitize_positive_int(page_limit, PAGE_LIMIT)
        while True:
            page_count += 1
            if page_count > MAX_PAGES:
                raise RuntimeError("分页次数过多，已中断加载（可能是分页游标无效）")
            payload = http_get_json(
                url,
                params={"limit": effective_page_limit, "lastFileName": last_file_name},
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
                last_path = str(entries[-1].get("FullPath", ""))
                next_cursor = basename(last_path)
            # 保护逻辑：如果游标不变化，说明服务端一直返回同一页，避免死循环。
            if next_cursor == last_file_name or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            last_file_name = next_cursor
            if payload.get("ShouldDisplayLoadMore") is False:
                break
            if len(entries) < effective_page_limit:
                break
        return all_entries

    def preview_file(self, base_url: str, full_path: str) -> str:
        url = join_url(base_url, full_path)
        data = http_get_bytes(url)
        return data.decode("utf-8", errors="replace")

    def download_file_to_local(
        self,
        base_url: str,
        full_path: str,
        local_file_path: str,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        url = join_url(base_url, full_path)
        req = urllib.request.Request(url, method="GET")
        parent_dir = os.path.dirname(local_file_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(local_file_path, "wb") as f:
                while True:
                    if cancel_check is not None and cancel_check():
                        raise RuntimeError("下载已取消")
                    chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)


class DirectoryLoadWorker(QObject):
    finished = Signal(list)
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
            )
            self.finished.emit(entries)
        except urllib.error.HTTPError as e:
            self.error.emit(f"HTTP 错误: {e.code} {e.reason}")
        except urllib.error.URLError as e:
            self.error.emit(f"网络错误: {e.reason}")
        except Exception as e:
            self.error.emit(f"加载异常: {e}")


class PreviewDialog(QDialog):
    def __init__(
        self,
        title: str,
        content: str,
        on_save_as: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 600)
        self._on_save_as = on_save_as

        text = QPlainTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(content)

        buttons = QDialogButtonBox(self)
        self.save_btn = buttons.addButton(
            "另存为本地文件", QDialogButtonBox.ButtonRole.ActionRole
        )
        close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.save_btn.setEnabled(on_save_as is not None)
        self.save_btn.clicked.connect(self.handle_save_as)
        close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout()
        layout.addWidget(text)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self.setWindowIcon(QIcon(get_resource_path(os.path.join("resource", "seaweedfs.png"))))

    def handle_save_as(self) -> None:
        if self._on_save_as is not None:
            self._on_save_as()


class EntryDetailDialog(QDialog):
    def __init__(self, title: str, details_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(920, 680)
        self.setWindowIcon(QIcon(get_resource_path(os.path.join("resource", "seaweedfs.png"))))

        text = QPlainTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(details_text)

        buttons = QDialogButtonBox(self)
        copy_btn = buttons.addButton("复制全部", QDialogButtonBox.ButtonRole.ActionRole)
        close_btn = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(text.toPlainText()))
        close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout()
        layout.addWidget(text)
        layout.addWidget(buttons)
        self.setLayout(layout)


class SaveDirectoryWorker(QObject):
    progress = Signal(str, int, int, int, str)
    finished = Signal(dict)
    cancelled = Signal(str)
    error = Signal(str)

    def __init__(self, client: SeaweedClient, base_url: str, source_dir: str, target_dir: str, page_limit: int):
        super().__init__()
        self.client = client
        self.base_url = base_url
        self.source_dir = normalize_dir_path(source_dir)
        self.target_dir = target_dir
        self.page_limit = page_limit
        self._cancelled = False

    def request_cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        try:
            files = self.collect_files()
            total_files = len(files)
            downloaded = 0
            source_prefix = self.source_dir.rstrip("/")
            if source_prefix == "":
                source_prefix = "/"

            for full_path in files:
                if self.is_cancelled():
                    self.cancelled.emit("用户已中断保存任务")
                    return
                rel_path = self.make_relative_path(full_path, source_prefix)
                local_path = os.path.join(self.target_dir, rel_path.replace("/", os.sep))
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
        except RuntimeError as e:
            if "取消" in str(e):
                self.cancelled.emit("用户已中断保存任务")
            else:
                self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"保存失败: {e}")

    def collect_files(self) -> List[str]:
        queue: List[str] = [self.source_dir]
        files: List[str] = []
        scanned_dirs = 0
        while queue:
            if self.is_cancelled():
                raise RuntimeError("下载已取消")
            current = queue.pop(0)
            entries = self.client.list_dir(self.base_url, current, self.page_limit)
            scanned_dirs += 1
            for entry in entries:
                full_path = normalize_dir_path(str(entry.get("FullPath", "")))
                if not full_path:
                    continue
                if is_directory(entry):
                    queue.append(full_path)
                else:
                    files.append(full_path)
            self.progress.emit("scan", scanned_dirs, len(files), 0, current)
        return files

    @staticmethod
    def make_relative_path(full_path: str, source_prefix: str) -> str:
        normalized = normalize_dir_path(full_path)
        prefix = source_prefix.rstrip("/")
        if prefix and normalized.startswith(prefix + "/"):
            return normalized[len(prefix) + 1 :]
        return normalized.lstrip("/")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SeaweedFS 文件浏览器")
        self.resize(1080, 720)
        self.setWindowIcon(QIcon(get_resource_path(os.path.join("resource", "seaweedfs.png"))))

        self.client = SeaweedClient()
        self.config = load_config()
        self.current_dir = normalize_dir_path(self.config.root_dir)
        self.entries: List[Dict[str, Any]] = []
        self._loader_thread: Optional[QThread] = None
        self._loader_worker: Optional[DirectoryLoadWorker] = None
        self._loading_dialog: Optional[QProgressDialog] = None
        self._save_thread: Optional[QThread] = None
        self._save_worker: Optional[SaveDirectoryWorker] = None
        self._save_dialog: Optional[QProgressDialog] = None

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout()
        root.setLayout(layout)

        top_row = QHBoxLayout()
        self.base_url_input = QComboBox()
        self.base_url_input.setEditable(True)
        self.base_url_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        base_edit = self.base_url_input.lineEdit()
        if base_edit is not None:
            base_edit.setPlaceholderText("例如: http://10.1.23.81:38888")
        self.reload_combo_items(self.base_url_input, self.config.base_url_history, self.config.base_url)
        top_row.addWidget(QLabel("服务地址:"))
        top_row.addWidget(self.base_url_input, 1)
        self.open_config_btn = QPushButton("打开配置目录")
        top_row.addWidget(self.open_config_btn)
        layout.addLayout(top_row)

        dir_row = QHBoxLayout()
        self.root_dir_input = QComboBox()
        self.root_dir_input.setEditable(True)
        self.root_dir_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        root_edit = self.root_dir_input.lineEdit()
        if root_edit is not None:
            root_edit.setPlaceholderText("例如: /buckets/cax-dev/PARTING/")
        self.reload_combo_items(self.root_dir_input, self.config.root_dir_history, self.config.root_dir)
        self.load_root_btn = QPushButton("加载根目录")
        dir_row.addWidget(QLabel("根目录:"))
        dir_row.addWidget(self.root_dir_input, 1)
        dir_row.addWidget(self.load_root_btn)
        layout.addLayout(dir_row)

        search_row = QHBoxLayout()
        self.search_input = QComboBox()
        self.search_input.setEditable(True)
        self.search_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        search_edit = self.search_input.lineEdit()
        if search_edit is not None:
            search_edit.setPlaceholderText("当前页中搜索（按名称过滤）")
        self.reload_combo_items(self.search_input, self.config.search_history, "")
        self.search_btn = QPushButton("重新搜索")
        search_row.addWidget(QLabel("搜索:"))
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        self.path_label = QLabel()
        layout.addWidget(self.path_label)

        browser_toolbar = QHBoxLayout()
        self.up_btn = QPushButton("返回上级")
        self.refresh_btn = QPushButton("刷新当前目录")
        self.save_dir_btn = QPushButton("保存到本地")
        browser_toolbar.addWidget(self.up_btn)
        browser_toolbar.addWidget(self.refresh_btn)
        browser_toolbar.addWidget(self.save_dir_btn)
        browser_toolbar.addStretch(1)
        layout.addLayout(browser_toolbar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(9)
        self.tree.setHeaderLabels(
            ["名称", "类型", "大小", "修改时间", "创建时间", "MIME类型", "MD5值", "权限模式", "分块数"]
        )
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.tree, 1)

        self.init_menu_bar()
        self.statusBar().showMessage("就绪")

        self.load_root_btn.clicked.connect(self.load_root_directory)
        self.refresh_btn.clicked.connect(self.refresh_current_directory)
        self.search_btn.clicked.connect(self.apply_search)
        self.up_btn.clicked.connect(self.go_up_directory)
        self.save_dir_btn.clicked.connect(self.save_current_directory_to_local)
        self.open_config_btn.clicked.connect(self.open_config_directory)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)

        self.refresh_current_directory()

    def init_menu_bar(self) -> None:
        help_menu = self.menuBar().addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def show_about_dialog(self) -> None:
        about_text = (
            "author: ganjb\nganjb_at_hustcad_dot_com"
        )
        dialog_parent = self if self.isVisible() else None
        QMessageBox.information(dialog_parent, "关于", about_text)

    def get_base_url(self) -> str:
        return normalize_base_url(self.base_url_input.currentText())

    def get_root_dir(self) -> str:
        return normalize_dir_path(self.root_dir_input.currentText())

    def get_search_text(self) -> str:
        return self.search_input.currentText().strip()

    def save_current_config(self) -> None:
        self.config.base_url = self.get_base_url()
        self.config.root_dir = self.get_root_dir()
        self.config.page_limit = sanitize_positive_int(self.config.page_limit, PAGE_LIMIT)
        save_config(self.config)

    def remember_input_histories(self, include_search: bool = False) -> None:
        self.config.base_url_history = update_history(self.config.base_url_history, self.get_base_url())
        self.config.root_dir_history = update_history(self.config.root_dir_history, self.get_root_dir())
        if include_search:
            self.config.search_history = update_history(self.config.search_history, self.get_search_text())
        self.reload_combo_items(self.base_url_input, self.config.base_url_history, self.get_base_url())
        self.reload_combo_items(self.root_dir_input, self.config.root_dir_history, self.get_root_dir())
        if include_search:
            self.reload_combo_items(self.search_input, self.config.search_history, self.get_search_text())
        self.save_current_config()

    @staticmethod
    def reload_combo_items(combo: QComboBox, items: List[str], current_text: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        for value in items[:MAX_HISTORY]:
            combo.addItem(value)
        combo.setCurrentText(current_text)
        combo.blockSignals(False)

    def open_config_directory(self) -> None:
        config_dir = os.path.dirname(get_config_path())
        try:
            open_path_in_file_explorer(config_dir)
        except Exception as e:
            QMessageBox.critical(self, "打开失败", f"无法打开配置目录:\n{e}")

    def load_root_directory(self) -> None:
        self.remember_input_histories(include_search=False)
        self.current_dir = self.get_root_dir()
        self.refresh_current_directory()

    def refresh_current_directory(self) -> None:
        base_url = self.get_base_url()
        if not base_url:
            QMessageBox.warning(self, "参数错误", "地址不能为空")
            return
        if self._save_thread and self._save_thread.isRunning():
            QMessageBox.information(self, "任务进行中", "当前正在保存到本地，请稍候或先中断。")
            return
        if self._loader_thread and self._loader_thread.isRunning():
            self.statusBar().showMessage("正在加载，请稍候...")
            return
        self.remember_input_histories(include_search=False)
        self.statusBar().showMessage("正在加载...")
        self.path_label.setText(f"当前位置: {self.current_dir}")
        self.start_directory_load(base_url, self.current_dir)

    def start_directory_load(self, base_url: str, dir_path: str) -> None:
        self.set_loading_ui(True)
        self._loading_dialog = QProgressDialog("正在重新加载目录，请稍候...", "", 0, 0, self)
        self._loading_dialog.setWindowTitle("加载中")
        self._loading_dialog.setCancelButton(None)
        self._loading_dialog.setWindowModality(Qt.WindowModality.NonModal)
        self._loading_dialog.setMinimumDuration(0)
        self._loading_dialog.setAutoClose(False)
        self._loading_dialog.setAutoReset(False)
        self._loading_dialog.show()

        self._loader_thread = QThread(self)
        self._loader_worker = DirectoryLoadWorker(
            self.client,
            base_url,
            dir_path,
            self.config.page_limit,
        )
        self._loader_worker.moveToThread(self._loader_thread)

        self._loader_thread.started.connect(self._loader_worker.run)
        self._loader_worker.progress.connect(self.on_directory_load_progress)
        self._loader_worker.finished.connect(self.on_directory_load_finished)
        self._loader_worker.error.connect(self.on_directory_load_failed)
        self._loader_worker.finished.connect(self._loader_thread.quit)
        self._loader_worker.error.connect(self._loader_thread.quit)
        self._loader_thread.finished.connect(self._loader_worker.deleteLater)
        self._loader_thread.finished.connect(self._loader_thread.deleteLater)
        self._loader_thread.finished.connect(self.on_directory_load_thread_cleaned)
        self._loader_thread.start()

    def on_directory_load_finished(self, entries: List[Dict[str, Any]]) -> None:
        self.entries = entries
        self.render_entries()
        self.statusBar().showMessage(f"已加载 {len(entries)} 条")

    def on_directory_load_progress(self, count: int) -> None:
        if self._loading_dialog is not None:
            self._loading_dialog.setLabelText(f"正在重新加载目录... 已加载 {count} 条")
        self.statusBar().showMessage(f"正在加载... 已加载 {count} 条")

    def on_directory_load_failed(self, message: str) -> None:
        QMessageBox.critical(self, "加载失败", message)
        self.statusBar().showMessage("加载失败")

    def on_directory_load_thread_cleaned(self) -> None:
        self._loader_thread = None
        self._loader_worker = None
        if self._loading_dialog is not None:
            self._loading_dialog.close()
            self._loading_dialog.deleteLater()
            self._loading_dialog = None
        self.set_loading_ui(False)

    def set_loading_ui(self, loading: bool) -> None:
        self.base_url_input.setEnabled(not loading)
        self.root_dir_input.setEnabled(not loading)
        self.open_config_btn.setEnabled(not loading)
        self.load_root_btn.setEnabled(not loading)
        self.refresh_btn.setEnabled(not loading)
        self.save_dir_btn.setEnabled(not loading)
        self.search_btn.setEnabled(not loading)
        self.search_input.setEnabled(not loading)
        self.up_btn.setEnabled(not loading)
        self.tree.setEnabled(not loading)

    def render_entries(self) -> None:
        sort_column = self.tree.sortColumn()
        sort_order = self.tree.header().sortIndicatorOrder()
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for entry in self.entries:
            full_path = str(entry.get("FullPath", ""))
            name = basename(full_path)
            dir_flag = is_directory(entry)
            type_text = "文件夹" if dir_flag else "文件"
            file_size_raw = sanitize_positive_int(entry.get("FileSize", 0), 0) if not dir_flag else 0
            size = format_size(file_size_raw) if not dir_flag else ""
            mtime_raw = parse_time_sort_value(entry.get("Mtime", 0))
            crtime_raw = parse_time_sort_value(entry.get("Crtime", 0))
            mtime = format_time(entry.get("Mtime"))
            crtime = format_time(entry.get("Crtime"))
            mime = str(entry.get("Mime", "")) if not dir_flag else ""
            md5 = str(entry.get("Md5", "")) if not dir_flag else ""
            mode_value = entry.get("Mode", "")
            mode_text = str(mode_value)
            mode_sort = parse_mode_value(mode_value)
            chunks = entry.get("chunks") or []
            chunks_count = len(chunks) if isinstance(chunks, list) and not dir_flag else 0
            chunks_text = str(chunks_count) if chunks_count else ""
            item = SortableTreeWidgetItem(
                [name, type_text, size, mtime, crtime, mime, md5, mode_text, chunks_text]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, full_path)
            item.setData(1, Qt.ItemDataRole.UserRole, dir_flag)
            item.setData(2, Qt.ItemDataRole.UserRole, entry)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, name.lower())
            item.setData(1, Qt.ItemDataRole.UserRole + 1, type_text)
            item.setData(2, Qt.ItemDataRole.UserRole + 1, file_size_raw)
            item.setData(3, Qt.ItemDataRole.UserRole + 1, mtime_raw)
            item.setData(4, Qt.ItemDataRole.UserRole + 1, crtime_raw)
            item.setData(5, Qt.ItemDataRole.UserRole + 1, mime.lower())
            item.setData(6, Qt.ItemDataRole.UserRole + 1, md5.lower())
            item.setData(7, Qt.ItemDataRole.UserRole + 1, mode_sort if mode_sort is not None else mode_text)
            item.setData(8, Qt.ItemDataRole.UserRole + 1, chunks_count)
            tooltip_lines = [
                f"FullPath: {full_path}",
                f"Mode: {mode_text}",
                f"Mtime: {entry.get('Mtime', '')}",
                f"Crtime: {entry.get('Crtime', '')}",
                f"FileSize: {entry.get('FileSize', '')}",
                f"Md5: {md5}",
                f"Chunks: {chunks_text}",
            ]
            item.setToolTip(0, "\n".join(tooltip_lines))
            self.tree.addTopLevelItem(item)
        self.tree.setSortingEnabled(True)
        self.tree.sortItems(sort_column, sort_order)

    def apply_search(self) -> None:
        self.remember_input_histories(include_search=True)
        text = self.get_search_text().lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item is None:
                continue
            name = item.text(0).lower()
            item.setHidden(text not in name if text else False)

    def on_item_double_clicked(self, item: QTreeWidgetItem) -> None:
        full_path = str(item.data(0, Qt.ItemDataRole.UserRole))
        is_dir = bool(item.data(1, Qt.ItemDataRole.UserRole))
        if is_dir:
            self.current_dir = normalize_dir_path(full_path)
            self.refresh_current_directory()
            return
        self.open_preview(full_path)

    def show_tree_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        details_action = menu.addAction("查看详细信息")
        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == details_action:
            self.open_entry_details(item)

    def open_entry_details(self, item: QTreeWidgetItem) -> None:
        entry = item.data(2, Qt.ItemDataRole.UserRole)
        if not isinstance(entry, dict):
            return
        full_path = str(entry.get("FullPath", item.text(0)))
        details_json = json.dumps(entry, ensure_ascii=False, indent=2)
        details_text = f"FullPath: {full_path}\n\n{details_json}"
        dlg = EntryDetailDialog(f"详细信息: {full_path}", details_text, self)
        dlg.exec()

    def go_up_directory(self) -> None:
        root_dir = self.get_root_dir().rstrip("/")
        current = self.current_dir.rstrip("/")
        if current == root_dir:
            return
        parts = [p for p in current.split("/") if p]
        if not parts:
            self.current_dir = self.get_root_dir()
        else:
            parts = parts[:-1]
            self.current_dir = "/" + "/".join(parts) if parts else "/"
        if not self.current_dir.startswith(root_dir):
            self.current_dir = self.get_root_dir()
        self.refresh_current_directory()

    def open_preview(self, full_path: str) -> None:
        try:
            base_url = self.get_base_url()
            text = self.client.preview_file(base_url, full_path)
            dlg = PreviewDialog(
                f"预览: {full_path}",
                text,
                on_save_as=lambda: self.save_single_file_to_local(full_path),
                parent=self,
            )
            dlg.exec()
        except urllib.error.HTTPError as e:
            QMessageBox.critical(self, "预览失败", f"{e.code} {e.reason}")
        except urllib.error.URLError as e:
            QMessageBox.critical(self, "预览失败", str(e.reason))
        except UnicodeDecodeError:
            QMessageBox.warning(self, "预览失败", "该文件不是文本，或编码不支持。")
        except Exception as e:
            QMessageBox.critical(self, "预览失败", str(e))

    def save_single_file_to_local(self, full_path: str) -> None:
        default_name = basename(full_path)
        save_path, _ = QFileDialog.getSaveFileName(self, "另存为", default_name, "所有文件 (*)")
        if not save_path:
            return
        progress = QProgressDialog("正在保存文件...", "中断", 0, 0, self)
        progress.setWindowTitle("保存中")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        try:
            self.client.download_file_to_local(
                self.get_base_url(),
                full_path,
                save_path,
                cancel_check=progress.wasCanceled,
            )
            if progress.wasCanceled():
                if os.path.exists(save_path):
                    try:
                        os.remove(save_path)
                    except Exception:
                        pass
                QMessageBox.information(self, "已中断", "文件保存已中断。")
            else:
                QMessageBox.information(self, "保存成功", f"文件已保存到:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
        finally:
            progress.close()
            progress.deleteLater()

    def save_current_directory_to_local(self) -> None:
        if self._loader_thread and self._loader_thread.isRunning():
            QMessageBox.information(self, "任务进行中", "目录正在加载中，请稍后再保存。")
            return
        if self._save_thread and self._save_thread.isRunning():
            QMessageBox.information(self, "任务进行中", "已存在保存任务，请先等待完成或中断。")
            return
        base_url = self.get_base_url()
        if not base_url:
            QMessageBox.warning(self, "参数错误", "地址不能为空")
            return
        target_dir = QFileDialog.getExistingDirectory(self, "选择本地保存目录")
        if not target_dir:
            return

        self.set_loading_ui(True)
        self._save_dialog = QProgressDialog("准备扫描目录...", "中断", 0, 0, self)
        self._save_dialog.setWindowTitle("递归保存中")
        self._save_dialog.setWindowModality(Qt.WindowModality.NonModal)
        self._save_dialog.setMinimumDuration(0)
        self._save_dialog.setAutoClose(False)
        self._save_dialog.setAutoReset(False)
        self._save_dialog.show()

        self._save_thread = QThread(self)
        self._save_worker = SaveDirectoryWorker(
            self.client,
            base_url,
            self.current_dir,
            target_dir,
            self.config.page_limit,
        )
        self._save_worker.moveToThread(self._save_thread)

        self._save_thread.started.connect(self._save_worker.run)
        self._save_worker.progress.connect(self.on_save_progress)
        self._save_worker.finished.connect(self.on_save_finished)
        self._save_worker.cancelled.connect(self.on_save_cancelled)
        self._save_worker.error.connect(self.on_save_failed)
        self._save_dialog.canceled.connect(self._save_worker.request_cancel)

        self._save_worker.finished.connect(self._save_thread.quit)
        self._save_worker.cancelled.connect(self._save_thread.quit)
        self._save_worker.error.connect(self._save_thread.quit)
        self._save_thread.finished.connect(self._save_worker.deleteLater)
        self._save_thread.finished.connect(self._save_thread.deleteLater)
        self._save_thread.finished.connect(self.on_save_thread_cleaned)
        self._save_thread.start()
        self.statusBar().showMessage("开始递归保存当前目录...")

    def on_save_progress(
        self, phase: str, scanned_dirs: int, total_files: int, downloaded_files: int, current: str
    ) -> None:
        if self._save_dialog is None:
            return
        if phase == "scan":
            self._save_dialog.setRange(0, 0)
            self._save_dialog.setLabelText(
                f"正在扫描目录...\n已扫描目录: {scanned_dirs}\n已发现文件: {total_files}\n当前: {current}"
            )
            self.statusBar().showMessage(f"扫描中... 目录 {scanned_dirs}，文件 {total_files}")
            return
        total = max(total_files, 1)
        self._save_dialog.setRange(0, total)
        self._save_dialog.setValue(downloaded_files)
        self._save_dialog.setLabelText(
            f"正在下载文件...\n进度: {downloaded_files}/{total_files}\n当前: {current}"
        )
        self.statusBar().showMessage(f"下载中... {downloaded_files}/{total_files}")

    def on_save_finished(self, result: Dict[str, Any]) -> None:
        total_files = int(result.get("total_files", 0))
        downloaded_files = int(result.get("downloaded_files", 0))
        target_dir = str(result.get("target_dir", ""))
        QMessageBox.information(
            self,
            "保存完成",
            f"递归保存已完成。\n文件: {downloaded_files}/{total_files}\n目录: {target_dir}",
        )
        self.statusBar().showMessage(f"保存完成: {downloaded_files}/{total_files}")
        if target_dir:
            try:
                open_path_in_file_explorer(target_dir)
            except Exception as e:
                QMessageBox.warning(self, "提示", f"保存完成，但自动打开目录失败:\n{e}")

    def on_save_cancelled(self, message: str) -> None:
        QMessageBox.information(self, "已中断", message)
        self.statusBar().showMessage("保存已中断")

    def on_save_failed(self, message: str) -> None:
        QMessageBox.critical(self, "保存失败", message)
        self.statusBar().showMessage("保存失败")

    def on_save_thread_cleaned(self) -> None:
        self._save_thread = None
        self._save_worker = None
        if self._save_dialog is not None:
            self._save_dialog.close()
            self._save_dialog.deleteLater()
            self._save_dialog = None
        self.set_loading_ui(False)


def main() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(get_resource_path(os.path.join("resource", "seaweedfs.png"))))
    app.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
    window = MainWindow()
    window.show_about_dialog()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
