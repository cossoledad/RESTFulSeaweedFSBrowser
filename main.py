import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

# 减少 Windows 下字体探测产生的大量告警输出。
os.environ.setdefault("QT_LOGGING_RULES", "qt.text.font.db.warning=false;qt.qpa.fonts.warning=false")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seaweed_browser.cache import LruCache
from seaweed_browser.client import SeaweedClient
from seaweed_browser.core import (
    APP_NAME,
    APP_VERSION,
    MAX_HISTORY,
    SUPPORTED_F3D_MODEL_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    basename,
    format_size,
    format_time,
    get_config_path,
    get_path_extension,
    is_directory,
    load_config,
    normalize_base_url,
    normalize_dir_path,
    parse_mode_value,
    parse_time_sort_value,
    sanitize_positive_int,
    save_config,
    update_history,
)
from seaweed_browser.tasks import (
    DirectoryLoadWorker,
    FileDownloadWorker,
    PreviewLoadWorker,
    SaveDirectoryWorker,
    TaskManager,
)
from seaweed_browser.resources import (
    get_app_window_icon,
    get_base_dir,
    get_windows_icon_path,
    is_bundled_app,
)
from seaweed_browser.widgets import (
    EntryDetailDialog,
    ImagePreviewDialog,
    PreviewDialog,
    SortableTreeWidgetItem,
)


WINDOW_ICON_HANDLES: List[int] = []
F3D_RUNTIME_DLL_NAMES = ["f3d.dll", "vcruntime140.dll", "zlib.dll"]


def open_path_in_file_explorer(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def get_preview_runtime_args() -> List[str]:
    if is_bundled_app():
        return [sys.executable]
    return [sys.executable, os.path.abspath(__file__)]


def ensure_f3d_runtime_layout() -> None:
    if not is_bundled_app():
        return
    base_dir = get_base_dir()
    f3d_bin_dir = os.path.join(base_dir, "f3d", "bin")
    if os.path.isdir(f3d_bin_dir):
        return

    copied_any = False
    os.makedirs(f3d_bin_dir, exist_ok=True)
    for dll_name in F3D_RUNTIME_DLL_NAMES:
        source_path = os.path.join(base_dir, dll_name)
        target_path = os.path.join(f3d_bin_dir, dll_name)
        if os.path.exists(source_path) and not os.path.exists(target_path):
            shutil.copy2(source_path, target_path)
            copied_any = True

    if not copied_any and not os.listdir(f3d_bin_dir):
        shutil.rmtree(os.path.join(base_dir, "f3d"), ignore_errors=True)


def load_windows_app_icon_handle() -> int:
    if not sys.platform.startswith("win"):
        return 0

    import ctypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010

    if is_bundled_app():
        small_icon = ctypes.c_void_p()
        large_icon = ctypes.c_void_p()
        extracted = shell32.ExtractIconExW(sys.executable, 0, ctypes.byref(large_icon), ctypes.byref(small_icon), 1)
        if extracted > 0:
            handle = large_icon.value or small_icon.value or 0
            if handle:
                return int(handle)

    icon_path = get_windows_icon_path()
    if not icon_path:
        return 0
    return int(user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE) or 0)




def launch_f3d_preview_subprocess(model_path: str, cleanup_dir: str) -> subprocess.Popen:
    args = get_preview_runtime_args() + ["--f3d-preview", model_path, "--cleanup-dir", cleanup_dir]
    popen_kwargs: Dict[str, Any] = {}
    if sys.platform.startswith("win"):
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(args, **popen_kwargs)


def apply_windows_window_icon_later() -> None:
    if not sys.platform.startswith("win"):
        return

    def worker() -> None:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        GCLP_HICON = -14
        GCLP_HICONSM = -34

        target_pid = kernel32.GetCurrentProcessId()
        icon_handle = load_windows_app_icon_handle()
        if not icon_handle:
            return
        WINDOW_ICON_HANDLES.append(icon_handle)

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        hwnd_list: List[int] = []

        def enum_windows_proc(hwnd, _lparam):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != target_pid or not user32.IsWindowVisible(hwnd):
                return True
            hwnd_list.append(hwnd)
            return True

        deadline = time.time() + 5.0
        while time.time() < deadline:
            hwnd_list.clear()
            user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)
            if hwnd_list:
                for hwnd in hwnd_list:
                    user32.SetClassLongPtrW(hwnd, GCLP_HICON, icon_handle)
                    user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, icon_handle)
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, icon_handle)
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, icon_handle)
            time.sleep(0.2)

    threading.Thread(target=worker, daemon=True).start()


def run_f3d_preview(model_path: str, cleanup_dir: str = "") -> int:
    ensure_f3d_runtime_layout()
    try:
        import f3d
    except ImportError:
        print("缺少依赖: f3d。请先执行 pip install f3d", file=sys.stderr)
        return 1

    try:
        engine = f3d.Engine.create()
        window_width = 960
        window_height = 720
        engine.window.set_window_name(f"{APP_NAME} - 模型预览")
        try:
            engine.window.size = (window_width, window_height)
        except Exception:
            pass
        if sys.platform.startswith("win"):
            try:
                import ctypes

                user32 = ctypes.windll.user32
                screen_w = user32.GetSystemMetrics(0)
                screen_h = user32.GetSystemMetrics(1)
                pos_x = max(0, (screen_w - window_width) // 2)
                pos_y = max(0, (screen_h - window_height) // 2)
                engine.window.set_position(pos_x, pos_y)
            except Exception:
                pass
        apply_windows_window_icon_later()
        try:
            engine.scene.add(model_path)
        except RuntimeError as e:
            raise RuntimeError(f"F3D 无法加载模型: {model_path}") from e
        try:
            camera = engine.window.camera
            camera.reset_to_bounds(0.9)
            camera.azimuth(random.choice([35, 55, 125, 145, 215, 235, 305, 325]))
            camera.elevation(random.choice([-25, -15, 15, 25, 35]))
            camera.set_current_as_default()
        except Exception:
            pass
        engine.interactor.start()
        return 0
    finally:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def check_f3d_runtime() -> int:
    """Validate the packaged F3D binding without opening a render window."""
    if is_bundled_app() and get_preview_runtime_args() != [sys.executable]:
        print("F3D 自检失败: 打包程序的预览子进程启动参数不正确", file=sys.stderr)
        return 1

    try:
        import f3d
    except Exception as e:
        print(f"F3D 自检失败: 无法导入 f3d: {e}", file=sys.stderr)
        return 1

    if not hasattr(f3d, "Engine"):
        print("F3D 自检失败: f3d.Engine 不存在", file=sys.stderr)
        return 1

    print(f"F3D 自检通过: {getattr(f3d, '__version__', 'unknown')}")
    return 0


@dataclass
class ModelPreviewProcess:
    process: subprocess.Popen
    temp_dir: str


class MainWindow(QMainWindow):
    DIRECTORY_LOAD_TASK = "directory-load"
    DIRECTORY_SAVE_TASK = "directory-save"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SeaweedFS 文件浏览器")
        self.resize(1080, 720)
        self.setWindowIcon(get_app_window_icon())

        self.client = SeaweedClient()
        self.config = load_config()
        self.current_dir = normalize_dir_path(self.config.root_dir)
        self.entries: List[Dict[str, Any]] = []
        self._directory_cache: LruCache[str, List[Dict[str, Any]]] = LruCache(
            self.config.directory_cache_max_entries
        )
        self._loading_dialog: Optional[QProgressDialog] = None
        self._save_dialog: Optional[QProgressDialog] = None
        self._file_save_dialogs: Dict[str, QProgressDialog] = {}
        self._preview_windows: Dict[str, QWidget] = {}
        self._preview_load_dialogs: Dict[str, QProgressDialog] = {}
        self._model_preview_processes: Dict[str, ModelPreviewProcess] = {}
        self._task_manager = TaskManager(self)
        self._task_manager.task_finished.connect(self.on_managed_task_finished)
        self._task_manager.all_finished.connect(self.on_all_tasks_finished)
        self._closing_after_task_cancel = False
        self._next_task_id = 0
        self._model_process_timer = QTimer(self)
        self._model_process_timer.setInterval(1000)
        self._model_process_timer.timeout.connect(self.reap_model_preview_processes)
        self._model_process_timer.start()

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
        self.refresh_btn = QPushButton("刷新当前目录 (F5)")
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
        self.refresh_action = QAction("刷新当前目录", self)
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.refresh_current_directory)
        self.addAction(self.refresh_action)
        self.statusBar().showMessage("就绪")

        self.load_root_btn.clicked.connect(self.load_root_directory)
        self.refresh_btn.clicked.connect(self.refresh_current_directory)
        self.search_btn.clicked.connect(self.apply_search)
        self.up_btn.clicked.connect(self.go_up_directory)
        self.save_dir_btn.clicked.connect(self.save_current_directory_to_local)
        self.open_config_btn.clicked.connect(self.open_config_directory)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)

        self.load_directory(self.current_dir, force_reload=False)

    def init_menu_bar(self) -> None:
        help_menu = self.menuBar().addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def show_about_dialog(self) -> None:
        about_text = (
            f"version: {APP_VERSION}\n"
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
        self.load_directory(self.get_root_dir(), force_reload=False)

    def refresh_current_directory(self) -> None:
        self.load_directory(self.current_dir, force_reload=True)

    def build_directory_cache_key(self, base_url: str, dir_path: str) -> str:
        return f"{normalize_base_url(base_url)}|{normalize_dir_path(dir_path)}"

    def try_apply_cached_directory(self, base_url: str, dir_path: str) -> bool:
        cache_key = self.build_directory_cache_key(base_url, dir_path)
        cached_entries = self._directory_cache.get(cache_key)
        if cached_entries is None:
            return False
        self.entries = list(cached_entries)
        self.render_entries()
        self.statusBar().showMessage(f"已从缓存加载 {len(cached_entries)} 条，按 F5 可重新加载")
        return True

    def load_directory(self, dir_path: str, force_reload: bool) -> None:
        base_url = self.get_base_url()
        if not base_url:
            QMessageBox.warning(self, "参数错误", "地址不能为空")
            return
        if self._task_manager.contains(self.DIRECTORY_SAVE_TASK):
            QMessageBox.information(self, "任务进行中", "当前正在保存到本地，请稍候或先中断。")
            return
        if self._task_manager.contains(self.DIRECTORY_LOAD_TASK):
            self.statusBar().showMessage("正在加载，请稍候...")
            return
        self.current_dir = normalize_dir_path(dir_path)
        self.remember_input_histories(include_search=False)
        self.path_label.setText(f"当前位置: {self.current_dir}")
        if not force_reload and self.try_apply_cached_directory(base_url, self.current_dir):
            return
        self.statusBar().showMessage("正在加载...")
        self.start_directory_load(base_url, self.current_dir)

    def start_directory_load(self, base_url: str, dir_path: str) -> None:
        self.set_loading_ui(True)
        self._loading_dialog = QProgressDialog(
            "正在重新加载目录，请稍候...",
            "取消",
            0,
            0,
            self,
        )
        self._loading_dialog.setWindowTitle("加载中")
        self._loading_dialog.setWindowModality(Qt.WindowModality.NonModal)
        self._loading_dialog.setMinimumDuration(0)
        self._loading_dialog.setAutoClose(False)
        self._loading_dialog.setAutoReset(False)
        self._loading_dialog.show()

        worker = DirectoryLoadWorker(
            self.client,
            base_url,
            dir_path,
            self.config.page_limit,
        )
        worker.progress.connect(self.on_directory_load_progress)
        worker.finished.connect(self.on_directory_load_finished)
        worker.cancelled.connect(self.on_directory_load_cancelled)
        worker.error.connect(self.on_directory_load_failed)
        self._loading_dialog.canceled.connect(
            lambda: self._task_manager.cancel(self.DIRECTORY_LOAD_TASK)
        )
        self._task_manager.start(
            self.DIRECTORY_LOAD_TASK,
            worker,
            (worker.finished, worker.cancelled, worker.error),
        )

    def on_directory_load_finished(self, entries: List[Dict[str, Any]]) -> None:
        self.entries = entries
        cache_key = self.build_directory_cache_key(self.get_base_url(), self.current_dir)
        self._directory_cache.put(cache_key, list(entries))
        self.render_entries()
        self.statusBar().showMessage(f"已加载 {len(entries)} 条")

    def on_directory_load_progress(self, count: int) -> None:
        if self._loading_dialog is not None:
            self._loading_dialog.setLabelText(f"正在重新加载目录... 已加载 {count} 条")
        self.statusBar().showMessage(f"正在加载... 已加载 {count} 条")

    def on_directory_load_failed(self, message: str) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, "加载失败", message)
        self.statusBar().showMessage("加载失败")

    def on_directory_load_cancelled(self) -> None:
        if not self._closing_after_task_cancel:
            self.statusBar().showMessage("目录加载已取消")

    def on_directory_load_thread_cleaned(self) -> None:
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
            self.load_directory(full_path, force_reload=False)
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
        preview_key = self.build_preview_window_key("details", full_path)
        if self.activate_preview_window(preview_key):
            return
        details_json = json.dumps(entry, ensure_ascii=False, indent=2)
        details_text = f"FullPath: {full_path}\n\n{details_json}"
        dlg = EntryDetailDialog(f"详细信息: {full_path}", details_text, self)
        self.show_preview_window(preview_key, dlg)

    def build_preview_window_key(self, preview_type: str, full_path: str) -> str:
        return f"{preview_type}:{self.get_base_url()}:{full_path}"

    @staticmethod
    def build_preview_task_key(preview_key: str) -> str:
        return f"preview-load:{preview_key}"

    def activate_preview_window(self, preview_key: str) -> bool:
        window = self._preview_windows.get(preview_key)
        if window is None:
            return False
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()
        return True

    def show_preview_window(
        self,
        preview_key: str,
        window: QWidget,
        on_destroyed: Optional[Callable[[], None]] = None,
    ) -> None:
        window.setWindowModality(Qt.WindowModality.NonModal)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        def handle_destroyed(*_: Any) -> None:
            self._preview_windows.pop(preview_key, None)
            if on_destroyed is not None:
                on_destroyed()

        window.destroyed.connect(handle_destroyed)
        self._preview_windows[preview_key] = window
        window.show()

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
        self.load_directory(self.current_dir, force_reload=False)

    def open_preview(self, full_path: str) -> None:
        extension = get_path_extension(full_path)
        if extension in SUPPORTED_F3D_MODEL_EXTENSIONS:
            preview_type = "model"
        elif extension in SUPPORTED_IMAGE_EXTENSIONS:
            preview_type = "image"
        else:
            preview_type = "text"

        preview_key = self.build_preview_window_key(preview_type, full_path)
        if self.activate_preview_window(preview_key):
            return
        base_url = self.get_base_url()
        if not base_url:
            QMessageBox.warning(self, "参数错误", "地址不能为空")
            return
        if preview_type == "model" and self.activate_model_preview_process(preview_key):
            return
        task_key = self.build_preview_task_key(preview_key)
        if self._task_manager.contains(task_key):
            dialog = self._preview_load_dialogs.get(preview_key)
            if dialog is not None:
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
            return
        if (
            self._task_manager.count("preview-load:")
            >= self.config.max_concurrent_preview_loads
        ):
            QMessageBox.information(
                self,
                "预览任务较多",
                f"最多同时准备 {self.config.max_concurrent_preview_loads} 个预览，"
                "请等待当前任务完成或先取消其中一个。",
            )
            return
        if preview_type == "model":
            try:
                import f3d  # noqa: F401
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "模型预览失败",
                    f"F3D 运行环境不可用，请检查安装或打包内容。\n\n{e}",
                )
                return
        self.start_preview_load(preview_key, preview_type, base_url, full_path)

    def start_preview_load(
        self,
        preview_key: str,
        preview_type: str,
        base_url: str,
        full_path: str,
    ) -> None:
        type_labels = {"text": "文本", "image": "图片", "model": "模型"}
        label = type_labels.get(preview_type, "文件")
        dialog = QProgressDialog(f"正在准备{label}预览...\n{full_path}", "取消", 0, 0, self)
        dialog.setWindowTitle(f"{label}预览加载中")
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.show()

        worker = PreviewLoadWorker(self.client, preview_type, base_url, full_path)
        task_key = self.build_preview_task_key(preview_key)
        self._preview_load_dialogs[preview_key] = dialog

        dialog.canceled.connect(lambda key=task_key: self._task_manager.cancel(key))
        dialog.canceled.connect(
            lambda key=preview_key: self.on_preview_cancel_requested(key)
        )
        worker.finished.connect(
            lambda result, key=preview_key: self.on_preview_load_finished(key, result)
        )
        worker.cancelled.connect(
            lambda key=preview_key: self.on_preview_load_cancelled(key)
        )
        worker.error.connect(
            lambda message, key=preview_key: self.on_preview_load_failed(key, message)
        )
        self._task_manager.start(
            task_key,
            worker,
            (worker.finished, worker.cancelled, worker.error),
        )
        self.statusBar().showMessage(f"正在准备{label}预览: {basename(full_path)}")

    def on_preview_cancel_requested(self, preview_key: str) -> None:
        dialog = self._preview_load_dialogs.get(preview_key)
        if dialog is not None:
            dialog.setLabelText("正在取消预览加载，请稍候...")

    def on_preview_load_finished(self, preview_key: str, result: Dict[str, Any]) -> None:
        preview_type = str(result.get("preview_type", ""))
        full_path = str(result.get("full_path", ""))
        temp_dir = str(result.get("temp_dir", ""))
        local_path = str(result.get("local_path", ""))
        task = self._task_manager.get(self.build_preview_task_key(preview_key))
        dialog = self._preview_load_dialogs.get(preview_key)
        if (
            task is not None
            and (
                task.worker.is_cancelled()
                or (dialog is not None and dialog.wasCanceled())
            )
        ):
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return
        if self._closing_after_task_cancel:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return
        try:
            if preview_type == "text":
                dlg = PreviewDialog(
                    f"预览: {full_path}",
                    str(result.get("content", "")),
                    on_save_as=lambda path=full_path: self.save_single_file_to_local(path),
                    parent=self,
                )
                self.show_preview_window(preview_key, dlg)
            elif preview_type == "image":
                dlg = ImagePreviewDialog(
                    f"图片预览: {full_path}",
                    local_path,
                    on_save_as=lambda path=full_path: self.save_single_file_to_local(path),
                    parent=self,
                )
                self.show_preview_window(
                    preview_key,
                    dlg,
                    on_destroyed=lambda path=temp_dir: shutil.rmtree(path, ignore_errors=True),
                )
                temp_dir = ""
            elif preview_type == "model":
                process = launch_f3d_preview_subprocess(local_path, temp_dir)
                self._model_preview_processes[preview_key] = ModelPreviewProcess(
                    process=process,
                    temp_dir=temp_dir,
                )
                temp_dir = ""
            else:
                raise RuntimeError(f"不支持的预览类型: {preview_type}")
            self.statusBar().showMessage(f"已打开预览: {basename(full_path)}")
        except Exception as e:
            if not self._closing_after_task_cancel:
                QMessageBox.critical(self, "预览失败", str(e))
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def on_preview_load_cancelled(self, preview_key: str) -> None:
        if not self._closing_after_task_cancel:
            self.statusBar().showMessage("预览加载已取消")

    def on_preview_load_failed(self, preview_key: str, message: str) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, "预览失败", message)
            self.statusBar().showMessage("预览加载失败")

    def on_preview_load_thread_cleaned(self, preview_key: str) -> None:
        dialog = self._preview_load_dialogs.pop(preview_key, None)
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()

    def activate_model_preview_process(self, preview_key: str) -> bool:
        record = self._model_preview_processes.get(preview_key)
        if record is None:
            return False
        if record.process.poll() is None:
            self.statusBar().showMessage("该模型预览窗口已经打开")
            return True
        self._model_preview_processes.pop(preview_key, None)
        shutil.rmtree(record.temp_dir, ignore_errors=True)
        return False

    def reap_model_preview_processes(self) -> None:
        for preview_key, record in list(self._model_preview_processes.items()):
            if record.process.poll() is None:
                continue
            self._model_preview_processes.pop(preview_key, None)
            shutil.rmtree(record.temp_dir, ignore_errors=True)

    def terminate_model_preview_processes(self) -> None:
        for record in list(self._model_preview_processes.values()):
            if record.process.poll() is None:
                try:
                    record.process.terminate()
                    record.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    record.process.kill()
                    try:
                        record.process.wait(timeout=2)
                    except Exception:
                        pass
                except Exception:
                    pass
            shutil.rmtree(record.temp_dir, ignore_errors=True)
        self._model_preview_processes.clear()

    def save_single_file_to_local(self, full_path: str) -> None:
        if (
            self._task_manager.count("file-save:")
            >= self.config.max_concurrent_file_saves
        ):
            QMessageBox.information(
                self,
                "保存任务较多",
                f"最多同时保存 {self.config.max_concurrent_file_saves} 个文件，"
                "请等待当前任务完成或先取消其中一个。",
            )
            return
        default_name = basename(full_path)
        save_path, _ = QFileDialog.getSaveFileName(self, "另存为", default_name, "所有文件 (*)")
        if not save_path:
            return
        self._next_task_id += 1
        task_key = f"file-save:{self._next_task_id}"
        progress = QProgressDialog("正在保存文件...", "中断", 0, 0, self)
        progress.setWindowTitle("保存中")
        progress.setWindowModality(Qt.WindowModality.NonModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        self._file_save_dialogs[task_key] = progress

        worker = FileDownloadWorker(
            self.client,
            self.get_base_url(),
            full_path,
            save_path,
        )
        progress.canceled.connect(lambda key=task_key: self._task_manager.cancel(key))
        worker.progress.connect(
            lambda downloaded, total, key=task_key: self.on_file_save_progress(
                key,
                downloaded,
                total,
            )
        )
        worker.finished.connect(
            lambda path, key=task_key: self.on_file_save_finished(key, path)
        )
        worker.cancelled.connect(
            lambda key=task_key: self.on_file_save_cancelled(key)
        )
        worker.error.connect(
            lambda message, key=task_key: self.on_file_save_failed(key, message)
        )
        self._task_manager.start(
            task_key,
            worker,
            (worker.finished, worker.cancelled, worker.error),
        )
        self.statusBar().showMessage(f"正在保存: {basename(full_path)}")

    def on_file_save_progress(
        self,
        task_key: str,
        downloaded: int,
        total: int,
    ) -> None:
        dialog = self._file_save_dialogs.get(task_key)
        if dialog is None:
            return
        if total > 0:
            percent = min(100, int(downloaded * 100 / total))
            dialog.setRange(0, 100)
            dialog.setValue(percent)
            dialog.setLabelText(
                f"正在保存文件...\n{format_size(downloaded)} / {format_size(total)}"
            )
        else:
            dialog.setRange(0, 0)
            dialog.setLabelText(f"正在保存文件...\n已下载 {format_size(downloaded)}")

    def on_file_save_finished(self, task_key: str, save_path: str) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.information(self, "保存成功", f"文件已保存到:\n{save_path}")
            self.statusBar().showMessage(f"保存完成: {save_path}")

    def on_file_save_cancelled(self, task_key: str) -> None:
        if not self._closing_after_task_cancel:
            self.statusBar().showMessage("文件保存已中断")

    def on_file_save_failed(self, task_key: str, message: str) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, "保存失败", message)
            self.statusBar().showMessage("文件保存失败")

    def save_current_directory_to_local(self) -> None:
        if self._task_manager.contains(self.DIRECTORY_LOAD_TASK):
            QMessageBox.information(self, "任务进行中", "目录正在加载中，请稍后再保存。")
            return
        if self._task_manager.contains(self.DIRECTORY_SAVE_TASK):
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

        worker = SaveDirectoryWorker(
            self.client,
            base_url,
            self.current_dir,
            target_dir,
            self.config.page_limit,
            self.config.directory_download_workers,
        )
        worker.progress.connect(self.on_save_progress)
        worker.finished.connect(self.on_save_finished)
        worker.cancelled.connect(self.on_save_cancelled)
        worker.error.connect(self.on_save_failed)
        self._save_dialog.canceled.connect(
            lambda: self._task_manager.cancel(self.DIRECTORY_SAVE_TASK)
        )
        self._task_manager.start(
            self.DIRECTORY_SAVE_TASK,
            worker,
            (worker.finished, worker.cancelled, worker.error),
        )
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
        if not self._closing_after_task_cancel:
            QMessageBox.information(
                self,
                "保存完成",
                f"递归保存已完成。\n文件: {downloaded_files}/{total_files}\n目录: {target_dir}",
            )
        self.statusBar().showMessage(f"保存完成: {downloaded_files}/{total_files}")
        if target_dir and not self._closing_after_task_cancel:
            try:
                open_path_in_file_explorer(target_dir)
            except Exception as e:
                QMessageBox.warning(self, "提示", f"保存完成，但自动打开目录失败:\n{e}")

    def on_save_cancelled(self, message: str) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.information(self, "已中断", message)
        self.statusBar().showMessage("保存已中断")

    def on_save_failed(self, message: str) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, "保存失败", message)
        self.statusBar().showMessage("保存失败")

    def on_save_thread_cleaned(self) -> None:
        if self._save_dialog is not None:
            self._save_dialog.close()
            self._save_dialog.deleteLater()
            self._save_dialog = None
        self.set_loading_ui(False)

    def on_managed_task_finished(self, task_key: str) -> None:
        if task_key == self.DIRECTORY_LOAD_TASK:
            self.on_directory_load_thread_cleaned()
            return
        if task_key == self.DIRECTORY_SAVE_TASK:
            self.on_save_thread_cleaned()
            return
        if task_key.startswith("preview-load:"):
            preview_key = task_key[len("preview-load:") :]
            self.on_preview_load_thread_cleaned(preview_key)
            return
        if task_key.startswith("file-save:"):
            dialog = self._file_save_dialogs.pop(task_key, None)
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()

    def on_all_tasks_finished(self) -> None:
        if self._closing_after_task_cancel:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event) -> None:
        for window in list(self._preview_windows.values()):
            window.close()

        if self._task_manager.has_active_tasks():
            self._closing_after_task_cancel = True
            self.setEnabled(False)
            self.statusBar().showMessage("正在取消后台任务并清理临时资源...")
            self._task_manager.cancel_all()
            for dialog in list(self._preview_load_dialogs.values()):
                dialog.setLabelText("正在取消预览加载，请稍候...")
                dialog.hide()
            for dialog in list(self._file_save_dialogs.values()):
                dialog.setLabelText("正在取消文件保存，请稍候...")
                dialog.hide()
            if self._loading_dialog is not None:
                self._loading_dialog.setLabelText("正在取消目录加载，请稍候...")
                self._loading_dialog.hide()
            if self._save_dialog is not None:
                self._save_dialog.setLabelText("正在取消目录保存，请稍候...")
                self._save_dialog.hide()
            event.ignore()
            return

        self._model_process_timer.stop()
        self.terminate_model_preview_processes()
        super().closeEvent(event)


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--check-f3d-runtime":
        return check_f3d_runtime()

    if len(sys.argv) >= 3 and sys.argv[1] == "--f3d-preview":
        model_path = sys.argv[2]
        cleanup_dir = ""
        if len(sys.argv) >= 5 and sys.argv[3] == "--cleanup-dir":
            cleanup_dir = sys.argv[4]
        return run_f3d_preview(model_path, cleanup_dir)

    app = QApplication(sys.argv)
    app.setWindowIcon(get_app_window_icon())
    app.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
