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
from PySide6.QtGui import QAction, QActionGroup, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
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
    PAGE_LIMIT,
    SUPPORTED_F3D_MODEL_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    basename,
    format_size,
    format_time,
    get_config_path,
    get_path_extension,
    is_directory,
    join_remote_child,
    load_config,
    normalize_base_url,
    normalize_dir_path,
    parse_mode_value,
    parse_time_sort_value,
    remote_path_is_within_root,
    sanitize_positive_int,
    save_config,
    update_history,
)
from seaweed_browser.i18n import (
    LANGUAGE_NAMES,
    get_language,
    set_language,
    tr,
)
from seaweed_browser.tasks import (
    CreateDirectoryWorker,
    DirectoryLoadWorker,
    FileDownloadWorker,
    PreviewLoadWorker,
    SaveDirectoryWorker,
    UploadBatchWorker,
)
from seaweed_browser.task_models import TaskError, TaskKind, TaskSpec
from seaweed_browser.task_presenter import TaskStatusController
from seaweed_browser.task_runtime import TaskManager
from seaweed_browser.task_widgets import TaskCenterDock
from seaweed_browser.uploads import UploadItem, build_upload_items
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
F3D_DLL_DIRECTORY_HANDLES: List[Any] = []
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
        # In some frozen runtimes ``sys.executable`` still refers to the Python
        # launcher used during compilation.  argv[0] is the executable the user
        # actually started, so retain it as a fallback for relocated releases.
        candidates = [sys.executable, os.path.abspath(sys.argv[0])]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return [candidate]
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


def configure_f3d_dll_search_path() -> None:
    """Make bundled F3D and its dependent DLLs discoverable on Windows."""
    if not sys.platform.startswith("win"):
        return
    f3d_bin_dir = os.path.join(get_base_dir(), "f3d", "bin")
    if not os.path.isdir(f3d_bin_dir):
        return

    current_path = os.environ.get("PATH", "")
    path_entries = current_path.split(os.pathsep) if current_path else []
    if os.path.normcase(f3d_bin_dir) not in {
        os.path.normcase(entry) for entry in path_entries
    }:
        os.environ["PATH"] = f3d_bin_dir + os.pathsep + current_path

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None and not F3D_DLL_DIRECTORY_HANDLES:
        # The returned handle must live for as long as f3d can load plugins.
        F3D_DLL_DIRECTORY_HANDLES.append(add_dll_directory(f3d_bin_dir))


def load_windows_app_icon_handles() -> tuple[int, int]:
    if not sys.platform.startswith("win"):
        return 0, 0

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010

    icon_path = get_windows_icon_path()
    if icon_path:
        # ctypes defaults pointer-returning Win32 APIs to a 32-bit c_int.  That
        # truncates HICON on 64-bit Windows, so declare the signature explicitly.
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        icon_sizes = (
            (user32.GetSystemMetrics(11), user32.GetSystemMetrics(12)),
            (user32.GetSystemMetrics(49), user32.GetSystemMetrics(50)),
        )
        handles = []
        for width, height in icon_sizes:
            handle = user32.LoadImageW(
                None,
                icon_path,
                IMAGE_ICON,
                width,
                height,
                LR_LOADFROMFILE,
            )
            handles.append(int(handle or 0))
        if handles[0] or handles[1]:
            return handles[0] or handles[1], handles[1] or handles[0]

    if is_bundled_app():
        shell32.ExtractIconExW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(wintypes.HICON),
            ctypes.POINTER(wintypes.HICON),
            wintypes.UINT,
        ]
        shell32.ExtractIconExW.restype = wintypes.UINT
        small_icon = wintypes.HICON()
        large_icon = wintypes.HICON()
        extracted = shell32.ExtractIconExW(
            sys.executable,
            0,
            ctypes.byref(large_icon),
            ctypes.byref(small_icon),
            1,
        )
        if extracted > 0:
            large = int(large_icon.value or small_icon.value or 0)
            small = int(small_icon.value or large_icon.value or 0)
            return large, small
    return 0, 0


def launch_f3d_preview_subprocess(model_path: str, cleanup_dir: str) -> subprocess.Popen:
    ensure_f3d_runtime_layout()
    configure_f3d_dll_search_path()
    args = get_preview_runtime_args() + ["--f3d-preview", model_path, "--cleanup-dir", cleanup_dir]
    popen_kwargs: Dict[str, Any] = {}
    if sys.platform.startswith("win"):
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(args, **popen_kwargs)


def apply_windows_window_icon_later() -> None:
    """Promote the F3D native window and apply the application icon."""
    if not sys.platform.startswith("win"):
        return

    def worker() -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        GCLP_HICON = -14
        GCLP_HICONSM = -34
        GWL_EXSTYLE = -20
        GWLP_HWNDPARENT = -8
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020

        LONG_PTR = ctypes.c_ssize_t
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = LONG_PTR
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
        user32.SetWindowLongPtrW.restype = LONG_PTR
        user32.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
        user32.SetClassLongPtrW.restype = LONG_PTR
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = wintypes.LPARAM
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        target_pid = kernel32.GetCurrentProcessId()
        large_icon, small_icon = load_windows_app_icon_handles()
        WINDOW_ICON_HANDLES.extend(
            handle for handle in (large_icon, small_icon) if handle
        )

        hwnd_list: List[int] = []

        def enum_windows_proc(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != target_pid or not user32.IsWindowVisible(hwnd):
                return True
            # The preview subprocess does not create a Qt main window, so every
            # visible top-level window belonging to it is an F3D/VTK window.
            # Do not match the caption: VTK is allowed to rewrite it after a
            # scene is loaded, which made the previous icon update miss it.
            hwnd_list.append(int(hwnd))
            return True

        deadline = time.time() + 5.0
        while time.time() < deadline:
            hwnd_list.clear()
            user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)
            if hwnd_list:
                for hwnd in hwnd_list:
                    # F3D/VTK can create an owned tool window, which Windows
                    # minimizes onto the desktop instead of the taskbar.  Turn
                    # it into a regular top-level application window.
                    ex_style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                    ex_style = (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex_style)
                    user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, 0)
                    if large_icon:
                        user32.SetClassLongPtrW(hwnd, GCLP_HICON, large_icon)
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, large_icon)
                    if small_icon:
                        user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, small_icon)
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small_icon)
                    user32.SetWindowPos(
                        hwnd,
                        0,
                        0,
                        0,
                        0,
                        0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
                    )
            time.sleep(0.2)

    threading.Thread(target=worker, daemon=True).start()


def run_f3d_preview(model_path: str, cleanup_dir: str = "") -> int:
    ensure_f3d_runtime_layout()
    configure_f3d_dll_search_path()
    try:
        import f3d
    except ImportError:
        print(tr("缺少依赖: f3d。请先执行 pip install f3d"), file=sys.stderr)
        return 1

    try:
        engine = f3d.Engine.create()
        window_width = 960
        window_height = 720
        window_title = f"{APP_NAME} - {tr('模型预览')}"
        engine.window.set_window_name(window_title)
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
            raise RuntimeError(
                tr("F3D 无法加载模型: {path}", path=model_path)
            ) from e
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
        print(
            tr("F3D 自检失败: 打包程序的预览子进程启动参数不正确"),
            file=sys.stderr,
        )
        return 1

    ensure_f3d_runtime_layout()
    configure_f3d_dll_search_path()
    try:
        import f3d
    except Exception as e:
        print(tr("F3D 自检失败: 无法导入 f3d: {error}", error=e), file=sys.stderr)
        return 1

    if not hasattr(f3d, "Engine"):
        print(tr("F3D 自检失败: f3d.Engine 不存在"), file=sys.stderr)
        return 1

    print(
        tr(
            "F3D 自检通过: {version}",
            version=getattr(f3d, "__version__", "unknown"),
        )
    )
    return 0


@dataclass
class ModelPreviewProcess:
    process: subprocess.Popen
    temp_dir: str


def ask_yes_no(
    parent: QWidget,
    title: str,
    text: str,
    default_yes: bool = True,
) -> bool:
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Icon.Question)
    dialog.setWindowTitle(title)
    dialog.setText(text)
    dialog.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    dialog.setDefaultButton(
        QMessageBox.StandardButton.Yes
        if default_yes
        else QMessageBox.StandardButton.No
    )
    yes_button = dialog.button(QMessageBox.StandardButton.Yes)
    no_button = dialog.button(QMessageBox.StandardButton.No)
    if yes_button is not None:
        yes_button.setText(tr("是"))
    if no_button is not None:
        no_button.setText(tr("否"))
    dialog.exec()
    return (
        dialog.standardButton(dialog.clickedButton())
        == QMessageBox.StandardButton.Yes
    )


def ask_text(parent: QWidget, title: str, label: str) -> tuple[str, bool]:
    dialog = QInputDialog(parent)
    dialog.setInputMode(QInputDialog.InputMode.TextInput)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setOkButtonText(tr("确定"))
    dialog.setCancelButtonText(tr("取消"))
    accepted = bool(dialog.exec())
    return dialog.textValue(), accepted


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1080, 720)
        self.setWindowIcon(get_app_window_icon())

        self.client = SeaweedClient()
        self.config = load_config()
        set_language(self.config.language)
        self.setWindowTitle(tr("SeaweedFS 文件浏览器"))
        self.current_dir = normalize_dir_path(self.config.root_dir)
        self.entries: List[Dict[str, Any]] = []
        self._directory_cache: LruCache[str, List[Dict[str, Any]]] = LruCache(
            self.config.directory_cache_max_entries
        )
        self._preview_windows: Dict[str, QWidget] = {}
        self._preview_load_tasks: Dict[str, str] = {}
        self._model_preview_processes: Dict[str, ModelPreviewProcess] = {}
        self._pending_directory_refreshes = set()
        self._pending_upload_retry: Optional[tuple[str, str, List[str]]] = None
        self._directory_load_task_id: Optional[str] = None
        self._directory_save_task_id: Optional[str] = None
        self._create_directory_task_id: Optional[str] = None
        self._create_directory_context: Optional[tuple[str, str]] = None
        self._upload_task_id: Optional[str] = None
        self._upload_context: Optional[tuple[str, str]] = None
        self._task_manager = TaskManager(
            self,
            history_limit=50,
            kind_limits={
                TaskKind.DIRECTORY_LOAD: 1,
                TaskKind.DIRECTORY_CREATE: 1,
                TaskKind.FILE_UPLOAD: 1,
                TaskKind.FILE_DOWNLOAD: self.config.max_concurrent_file_saves,
                TaskKind.DIRECTORY_DOWNLOAD: 1,
                TaskKind.PREVIEW_LOAD: self.config.max_concurrent_preview_loads,
            },
        )
        self._task_manager.task_succeeded.connect(self.on_task_succeeded)
        self._task_manager.task_failed.connect(self.on_task_failed)
        self._task_manager.task_cancelled.connect(self.on_task_cancelled)
        self._task_manager.task_cleaned.connect(self.on_task_cleaned)
        self._task_manager.all_finished.connect(self.on_all_tasks_finished)
        self._closing_after_task_cancel = False
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
            base_edit.setPlaceholderText(tr("例如: http://10.1.23.81:38888"))
        self.reload_combo_items(self.base_url_input, self.config.base_url_history, self.config.base_url)
        self.base_url_label = QLabel(tr("服务地址:"))
        top_row.addWidget(self.base_url_label)
        top_row.addWidget(self.base_url_input, 1)
        self.open_config_btn = QPushButton(tr("打开配置目录"))
        top_row.addWidget(self.open_config_btn)
        layout.addLayout(top_row)

        dir_row = QHBoxLayout()
        self.root_dir_input = QComboBox()
        self.root_dir_input.setEditable(True)
        self.root_dir_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        root_edit = self.root_dir_input.lineEdit()
        if root_edit is not None:
            root_edit.setPlaceholderText(tr("例如: /buckets/cax-dev/PARTING/"))
        self.reload_combo_items(self.root_dir_input, self.config.root_dir_history, self.config.root_dir)
        self.load_root_btn = QPushButton(tr("加载根目录"))
        self.root_dir_label = QLabel(tr("根目录:"))
        dir_row.addWidget(self.root_dir_label)
        dir_row.addWidget(self.root_dir_input, 1)
        dir_row.addWidget(self.load_root_btn)
        layout.addLayout(dir_row)

        search_row = QHBoxLayout()
        self.search_input = QComboBox()
        self.search_input.setEditable(True)
        self.search_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        search_edit = self.search_input.lineEdit()
        if search_edit is not None:
            search_edit.setPlaceholderText(tr("当前页中搜索（按名称过滤）"))
        self.reload_combo_items(self.search_input, self.config.search_history, "")
        self.search_btn = QPushButton(tr("重新搜索"))
        self.search_label = QLabel(tr("搜索:"))
        search_row.addWidget(self.search_label)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        self.path_label = QLabel()
        layout.addWidget(self.path_label)

        browser_toolbar = QHBoxLayout()
        self.up_btn = QPushButton(tr("返回上级"))
        self.refresh_btn = QPushButton(tr("刷新当前目录 (F5)"))
        self.save_dir_btn = QPushButton(tr("保存到本地"))
        self.create_dir_btn = QPushButton(tr("新建文件夹"))
        self.upload_files_btn = QPushButton(tr("上传文件"))
        browser_toolbar.addWidget(self.up_btn)
        browser_toolbar.addWidget(self.refresh_btn)
        browser_toolbar.addWidget(self.save_dir_btn)
        browser_toolbar.addWidget(self.create_dir_btn)
        browser_toolbar.addWidget(self.upload_files_btn)
        browser_toolbar.addStretch(1)
        layout.addLayout(browser_toolbar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(9)
        self.tree.setHeaderLabels(
            [
                tr("名称"),
                tr("类型"),
                tr("大小"),
                tr("修改时间"),
                tr("创建时间"),
                tr("MIME类型"),
                tr("MD5值"),
                tr("权限模式"),
                tr("分块数"),
            ]
        )
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.tree, 1)

        self.init_menu_bar()
        self.refresh_action = QAction(tr("刷新当前目录"), self)
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.refresh_current_directory)
        self.addAction(self.refresh_action)
        self._task_center = TaskCenterDock(self._task_manager, self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._task_center)
        self._task_center.hide()
        self._status_controller = TaskStatusController(
            self._task_manager,
            self.statusBar(),
            self._task_center.show_and_raise,
            self,
        )

        self.load_root_btn.clicked.connect(self.load_root_directory)
        self.refresh_btn.clicked.connect(self.refresh_current_directory)
        self.search_btn.clicked.connect(self.apply_search)
        self.up_btn.clicked.connect(self.go_up_directory)
        self.save_dir_btn.clicked.connect(self.save_current_directory_to_local)
        self.create_dir_btn.clicked.connect(self.create_remote_directory)
        self.upload_files_btn.clicked.connect(self.select_files_to_upload)
        self.open_config_btn.clicked.connect(self.open_config_directory)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)

        self.apply_language()
        self.load_directory(self.current_dir, force_reload=False)

    def init_menu_bar(self) -> None:
        self.language_menu = self.menuBar().addMenu(tr("语言"))
        self.language_action_group = QActionGroup(self)
        self.language_action_group.setExclusive(True)
        self.language_actions: Dict[str, QAction] = {}
        for code, native_name in LANGUAGE_NAMES.items():
            action = QAction(native_name, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, language=code: self.change_language(
                    language,
                    checked,
                )
            )
            self.language_action_group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action

        self.help_menu = self.menuBar().addMenu(tr("帮助"))
        self.about_action = QAction(tr("关于"), self)
        self.about_action.triggered.connect(self.show_about_dialog)
        self.help_menu.addAction(self.about_action)

    def change_language(self, language: str, checked: bool = True) -> None:
        if not checked or language == get_language():
            return
        self.config.language = set_language(language)
        self.save_current_config()
        self.apply_language()
        self._status_controller.show_transient(
            tr(
                "语言已切换为 {language}",
                language=LANGUAGE_NAMES[self.config.language],
            )
        )

    def apply_language(self) -> None:
        self.setWindowTitle(tr("SeaweedFS 文件浏览器"))
        self.base_url_label.setText(tr("服务地址:"))
        self.root_dir_label.setText(tr("根目录:"))
        self.search_label.setText(tr("搜索:"))
        base_edit = self.base_url_input.lineEdit()
        if base_edit is not None:
            base_edit.setPlaceholderText(tr("例如: http://10.1.23.81:38888"))
        root_edit = self.root_dir_input.lineEdit()
        if root_edit is not None:
            root_edit.setPlaceholderText(tr("例如: /buckets/cax-dev/PARTING/"))
        search_edit = self.search_input.lineEdit()
        if search_edit is not None:
            search_edit.setPlaceholderText(tr("当前页中搜索（按名称过滤）"))
        self.open_config_btn.setText(tr("打开配置目录"))
        self.load_root_btn.setText(tr("加载根目录"))
        self.search_btn.setText(tr("重新搜索"))
        self.up_btn.setText(tr("返回上级"))
        self.refresh_btn.setText(tr("刷新当前目录 (F5)"))
        self.save_dir_btn.setText(tr("保存到本地"))
        self.create_dir_btn.setText(tr("新建文件夹"))
        self.upload_files_btn.setText(tr("上传文件"))
        self.tree.setHeaderLabels(
            [
                tr("名称"),
                tr("类型"),
                tr("大小"),
                tr("修改时间"),
                tr("创建时间"),
                tr("MIME类型"),
                tr("MD5值"),
                tr("权限模式"),
                tr("分块数"),
            ]
        )
        self.refresh_action.setText(tr("刷新当前目录"))
        self.language_menu.setTitle(tr("语言"))
        self.help_menu.setTitle(tr("帮助"))
        self.about_action.setText(tr("关于"))
        for code, action in self.language_actions.items():
            action.setChecked(code == get_language())
        self.path_label.setText(tr("当前位置: {path}", path=self.current_dir))
        self._task_center.retranslate_ui()
        self._status_controller.retranslate_ui()
        if self.entries:
            self.render_entries()

    def show_about_dialog(self) -> None:
        about_text = (
            f"version: {APP_VERSION}\n"
            "author: ganjb\nganjb_at_hustcad_dot_com"
        )
        dialog_parent = self if self.isVisible() else None
        QMessageBox.information(dialog_parent, tr("关于"), about_text)

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
            QMessageBox.critical(
                self,
                tr("打开失败"),
                tr("无法打开配置目录:\n{error}", error=e),
            )

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
        self._status_controller.show_transient(
            tr(
                "已从缓存加载 {count} 条，按 F5 可重新加载",
                count=len(cached_entries),
            )
        )
        return True

    def is_task_active(self, task_id: Optional[str]) -> bool:
        return bool(task_id and self._task_manager.contains(task_id))

    def load_directory(self, dir_path: str, force_reload: bool) -> None:
        base_url = self.get_base_url()
        if not base_url:
            QMessageBox.warning(self, tr("参数错误"), tr("地址不能为空"))
            return
        if self.is_task_active(self._directory_load_task_id):
            self._status_controller.show_transient(tr("正在加载，请稍候..."))
            return
        self.current_dir = normalize_dir_path(dir_path)
        self.remember_input_histories(include_search=False)
        self.path_label.setText(tr("当前位置: {path}", path=self.current_dir))
        if not force_reload and self.try_apply_cached_directory(base_url, self.current_dir):
            return
        self.start_directory_load(base_url, self.current_dir)

    def start_directory_load(self, base_url: str, dir_path: str) -> None:
        self.set_loading_ui(True)
        worker = DirectoryLoadWorker(
            self.client,
            base_url,
            dir_path,
            self.config.page_limit,
        )
        self._directory_load_task_id = self._task_manager.start(
            TaskSpec(
                kind=TaskKind.DIRECTORY_LOAD,
                title=tr("加载目录"),
                detail=dir_path,
                dedup_key=f"directory-load:{base_url}:{dir_path}",
            ),
            worker,
        )

    def on_directory_load_finished(self, entries: List[Dict[str, Any]]) -> None:
        self.entries = entries
        cache_key = self.build_directory_cache_key(self.get_base_url(), self.current_dir)
        self._directory_cache.put(cache_key, list(entries))
        self.render_entries()
        self._status_controller.show_transient(
            tr("已加载 {count} 条", count=len(entries))
        )

    def on_directory_load_failed(self, error: TaskError) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, tr("加载失败"), error.message)
        self._status_controller.show_transient(tr("加载失败"))

    def on_directory_load_cancelled(self) -> None:
        if not self._closing_after_task_cancel:
            self._status_controller.show_transient(tr("目录加载已取消"))

    def on_directory_load_thread_cleaned(self) -> None:
        self._directory_load_task_id = None
        self.set_loading_ui(False)
        current_key = self.build_directory_cache_key(self.get_base_url(), self.current_dir)
        if current_key in self._pending_directory_refreshes:
            self._pending_directory_refreshes.discard(current_key)
            QTimer.singleShot(
                0,
                lambda path=self.current_dir: self.load_directory(path, force_reload=True),
            )

    def set_loading_ui(self, loading: bool) -> None:
        self.base_url_input.setEnabled(not loading)
        self.root_dir_input.setEnabled(not loading)
        self.open_config_btn.setEnabled(not loading)
        self.load_root_btn.setEnabled(not loading)
        self.refresh_btn.setEnabled(not loading)
        self.save_dir_btn.setEnabled(not loading)
        self.create_dir_btn.setEnabled(not loading)
        self.upload_files_btn.setEnabled(not loading)
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
            type_text = tr("文件夹") if dir_flag else tr("文件")
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
        menu = QMenu(self)
        create_action = menu.addAction(tr("新建文件夹"))
        upload_action = menu.addAction(tr("上传文件"))
        details_action = None
        if item is not None:
            menu.addSeparator()
            details_action = menu.addAction(tr("查看详细信息"))
        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == create_action:
            self.create_remote_directory()
        elif action == upload_action:
            self.select_files_to_upload()
        elif details_action is not None and action == details_action:
            self.open_entry_details(item)

    def existing_entries_by_name(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for entry in self.entries:
            full_path = str(entry.get("FullPath", "")).strip()
            if full_path:
                result[basename(full_path)] = entry
        return result

    def invalidate_remote_directory(self, base_url: str, directory: str) -> None:
        cache_key = self.build_directory_cache_key(base_url, directory)
        self._directory_cache.remove(cache_key)
        if (
            normalize_base_url(base_url) != self.get_base_url()
            or normalize_dir_path(directory) != self.current_dir
        ):
            return
        if self.is_task_active(self._directory_load_task_id):
            self._pending_directory_refreshes.add(cache_key)
            return
        QTimer.singleShot(
            0,
            lambda path=directory: self.load_directory(path, force_reload=True),
        )

    def create_remote_directory(self) -> None:
        if self.is_task_active(self._create_directory_task_id):
            QMessageBox.information(
                self,
                tr("任务进行中"),
                tr("已有目录创建任务正在执行。"),
            )
            return
        base_url = self.get_base_url()
        if not base_url:
            QMessageBox.warning(self, tr("参数错误"), tr("地址不能为空"))
            return
        if not remote_path_is_within_root(self.current_dir, self.get_root_dir()):
            QMessageBox.warning(
                self,
                tr("路径错误"),
                tr("当前目录超出配置的根目录，拒绝写入。"),
            )
            return
        name, accepted = ask_text(
            self,
            tr("新建文件夹"),
            tr("文件夹名称:"),
        )
        if not accepted:
            return
        try:
            target_path = join_remote_child(self.current_dir, name)
        except ValueError as error:
            QMessageBox.warning(self, tr("名称无效"), str(error))
            return

        existing = self.existing_entries_by_name().get(basename(target_path))
        if existing is not None:
            message = (
                tr("同名文件夹已经存在。")
                if is_directory(existing)
                else tr("同名文件已经存在，不能创建文件夹。")
            )
            QMessageBox.information(self, tr("名称冲突"), message)
            return

        parent_dir = self.current_dir
        worker = CreateDirectoryWorker(
            self.client,
            base_url,
            parent_dir,
            target_path,
        )
        self._create_directory_context = (base_url, parent_dir)
        self._create_directory_task_id = self._task_manager.start(
            TaskSpec(
                kind=TaskKind.DIRECTORY_CREATE,
                title=tr("创建文件夹"),
                detail=target_path,
                dedup_key=f"directory-create:{base_url}:{target_path}",
            ),
            worker,
        )

    def on_create_directory_finished(self, result: Dict[str, Any]) -> None:
        base_url = str(result.get("base_url", ""))
        parent_dir = str(result.get("parent_dir", ""))
        target_path = str(result.get("target_path", ""))
        self.invalidate_remote_directory(base_url, parent_dir)
        if not self._closing_after_task_cancel:
            self._status_controller.show_transient(
                tr("文件夹已创建: {name}", name=basename(target_path))
            )

    def on_create_directory_cancelled(self, base_url: str, parent_dir: str) -> None:
        self.invalidate_remote_directory(base_url, parent_dir)
        if not self._closing_after_task_cancel:
            self._status_controller.show_transient(
                tr("目录创建已取消，正在确认远程状态")
            )

    def on_create_directory_failed(
        self,
        base_url: str,
        parent_dir: str,
        error: TaskError,
    ) -> None:
        self.invalidate_remote_directory(base_url, parent_dir)
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, tr("创建文件夹失败"), error.message)
            self._status_controller.show_transient(tr("目录创建失败"))

    def select_files_to_upload(self) -> None:
        if self.is_task_active(self._upload_task_id):
            QMessageBox.information(
                self,
                tr("上传进行中"),
                tr("已有上传批次正在执行，请等待完成或先取消。"),
            )
            return
        base_url = self.get_base_url()
        if not base_url:
            QMessageBox.warning(self, tr("参数错误"), tr("地址不能为空"))
            return
        if not remote_path_is_within_root(self.current_dir, self.get_root_dir()):
            QMessageBox.warning(
                self,
                tr("路径错误"),
                tr("当前目录超出配置的根目录，拒绝写入。"),
            )
            return
        local_paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("选择要上传的文件"),
            "",
            tr("所有文件 (*)"),
        )
        if not local_paths:
            return
        self.prepare_upload_batch(local_paths, base_url, self.current_dir)

    def prepare_upload_batch(
        self,
        local_paths: List[str],
        base_url: str,
        target_dir: str,
        confirm_overwrite: bool = True,
    ) -> None:
        try:
            items = build_upload_items(local_paths, target_dir, join_remote_child)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("无法上传"), str(error))
            return

        existing = self.existing_entries_by_name()
        blocked_names = [
            basename(item.remote_path)
            for item in items
            if (
                basename(item.remote_path) in existing
                and is_directory(existing[basename(item.remote_path)])
            )
        ]
        if blocked_names:
            shown = "\n".join(blocked_names[:10])
            if len(blocked_names) > 10:
                shown += "\n" + tr(
                    "...另有 {count} 项",
                    count=len(blocked_names) - 10,
                )
            QMessageBox.warning(
                self,
                tr("存在目录冲突"),
                tr(
                    "以下名称已经是远程文件夹，不能作为文件覆盖:\n{names}",
                    names=shown,
                ),
            )
            blocked = set(blocked_names)
            items = [item for item in items if basename(item.remote_path) not in blocked]
        if not items:
            return

        overwrite_count = sum(
            1
            for item in items
            if basename(item.remote_path) in existing
            and not is_directory(existing[basename(item.remote_path)])
        )
        if confirm_overwrite and overwrite_count:
            should_overwrite = ask_yes_no(
                self,
                tr("确认覆盖上传"),
                tr(
                    "{count} 个同名文件将被覆盖。\n本次共上传 {total} 个文件，是否继续？",
                    count=overwrite_count,
                    total=len(items),
                ),
            )
            if not should_overwrite:
                return
        self.start_upload_batch(items, base_url, target_dir)

    def start_upload_batch(
        self,
        items: List[UploadItem],
        base_url: str,
        target_dir: str,
    ) -> None:
        if self.is_task_active(self._upload_task_id):
            return
        total_bytes = sum(item.size for item in items)
        worker = UploadBatchWorker(
            self.client,
            base_url,
            target_dir,
            items,
            self.config.upload_workers,
        )
        self._upload_context = (base_url, target_dir)
        self._upload_task_id = self._task_manager.start(
            TaskSpec(
                kind=TaskKind.FILE_UPLOAD,
                title=tr("上传 {count} 个文件", count=len(items)),
                detail=f"{target_dir} · {format_size(total_bytes)}",
                dedup_key="upload-batch",
            ),
            worker,
        )

    def on_upload_finished(self, result: Dict[str, Any]) -> None:
        base_url = str(result.get("base_url", ""))
        target_dir = str(result.get("target_dir", ""))
        uploaded_files = int(result.get("uploaded_files", 0))
        total_files = int(result.get("total_files", 0))
        failures = result.get("failures") or []
        self.invalidate_remote_directory(base_url, target_dir)
        if self._closing_after_task_cancel:
            return
        self._status_controller.show_transient(
            tr(
                "上传完成: {uploaded}/{total}",
                uploaded=uploaded_files,
                total=total_files,
            )
        )
        if not failures:
            return

        details = "\n".join(
            f"{basename(str(failure.get('remote_path', '')))}: {failure.get('error', '')}"
            for failure in failures[:8]
            if isinstance(failure, dict)
        )
        if len(failures) > 8:
            details += "\n" + tr(
                "...另有 {count} 项",
                count=len(failures) - 8,
            )
        should_retry = ask_yes_no(
            self,
            tr("部分文件上传失败"),
            tr(
                "已上传 {uploaded}/{total} 个文件。\n\n{details}\n\n是否重试失败项？",
                uploaded=uploaded_files,
                total=total_files,
                details=details,
            ),
        )
        if should_retry:
            retry_paths = [
                str(failure.get("local_path", ""))
                for failure in failures
                if isinstance(failure, dict) and failure.get("local_path")
            ]
            self._pending_upload_retry = (base_url, target_dir, retry_paths)

    def on_upload_cancelled(self, base_url: str, target_dir: str) -> None:
        self.invalidate_remote_directory(base_url, target_dir)
        if not self._closing_after_task_cancel:
            self._status_controller.show_transient(
                tr("上传已取消，正在确认远程状态")
            )

    def on_upload_failed(
        self,
        base_url: str,
        target_dir: str,
        error: TaskError,
    ) -> None:
        if isinstance(error.payload, dict):
            self.on_upload_finished(error.payload)
            return
        self.invalidate_remote_directory(base_url, target_dir)
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, tr("上传失败"), error.message)
            self._status_controller.show_transient(tr("上传失败"))

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
        dlg = EntryDetailDialog(
            tr("详细信息: {path}", path=full_path),
            details_text,
            self,
        )
        self.show_preview_window(preview_key, dlg)

    def build_preview_window_key(self, preview_type: str, full_path: str) -> str:
        return f"{preview_type}:{self.get_base_url()}:{full_path}"

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
            QMessageBox.warning(self, tr("参数错误"), tr("地址不能为空"))
            return
        if preview_type == "model" and self.activate_model_preview_process(preview_key):
            return
        existing_task_id = self._preview_load_tasks.get(preview_key)
        if self.is_task_active(existing_task_id):
            self._task_center.show_and_raise()
            return
        if (
            self._task_manager.count(TaskKind.PREVIEW_LOAD)
            >= self.config.max_concurrent_preview_loads
        ):
            QMessageBox.information(
                self,
                tr("预览任务较多"),
                tr(
                    "最多同时准备 {limit} 个预览，请等待当前任务完成或先取消其中一个。",
                    limit=self.config.max_concurrent_preview_loads,
                ),
            )
            return
        if preview_type == "model":
            try:
                import f3d  # noqa: F401
            except Exception as e:
                QMessageBox.critical(
                    self,
                    tr("模型预览失败"),
                    tr(
                        "F3D 运行环境不可用，请检查安装或打包内容。\n\n{error}",
                        error=e,
                    ),
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
        type_labels = {
            "text": tr("文本"),
            "image": tr("图片"),
            "model": tr("模型"),
        }
        label = type_labels.get(preview_type, tr("文件"))
        worker = PreviewLoadWorker(self.client, preview_type, base_url, full_path)
        task_id = self._task_manager.start(
            TaskSpec(
                kind=TaskKind.PREVIEW_LOAD,
                title=tr("{type}预览", type=label),
                detail=full_path,
                dedup_key=f"preview:{preview_key}",
            ),
            worker,
        )
        self._preview_load_tasks[preview_key] = task_id

    def on_preview_load_finished(self, preview_key: str, result: Dict[str, Any]) -> None:
        preview_type = str(result.get("preview_type", ""))
        full_path = str(result.get("full_path", ""))
        temp_dir = str(result.get("temp_dir", ""))
        local_path = str(result.get("local_path", ""))
        if self._closing_after_task_cancel:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return
        try:
            if preview_type == "text":
                dlg = PreviewDialog(
                    tr("预览: {path}", path=full_path),
                    str(result.get("content", "")),
                    on_save_as=lambda path=full_path: self.save_single_file_to_local(path),
                    parent=self,
                )
                self.show_preview_window(preview_key, dlg)
            elif preview_type == "image":
                dlg = ImagePreviewDialog(
                    tr("图片预览: {path}", path=full_path),
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
                raise RuntimeError(
                    tr("不支持的预览类型: {type}", type=preview_type)
                )
            self._status_controller.show_transient(
                tr("已打开预览: {name}", name=basename(full_path))
            )
        except Exception as e:
            if not self._closing_after_task_cancel:
                QMessageBox.critical(self, tr("预览失败"), str(e))
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def on_preview_load_cancelled(self, preview_key: str) -> None:
        if not self._closing_after_task_cancel:
            self._status_controller.show_transient(tr("预览加载已取消"))

    def on_preview_load_failed(self, preview_key: str, error: TaskError) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, tr("预览失败"), error.message)
            self._status_controller.show_transient(tr("预览加载失败"))

    def on_preview_load_thread_cleaned(self, preview_key: str) -> None:
        self._preview_load_tasks.pop(preview_key, None)

    def activate_model_preview_process(self, preview_key: str) -> bool:
        record = self._model_preview_processes.get(preview_key)
        if record is None:
            return False
        if record.process.poll() is None:
            self._status_controller.show_transient(tr("该模型预览窗口已经打开"))
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
            self._task_manager.count(TaskKind.FILE_DOWNLOAD)
            >= self.config.max_concurrent_file_saves
        ):
            QMessageBox.information(
                self,
                tr("保存任务较多"),
                tr(
                    "最多同时保存 {limit} 个文件，请等待当前任务完成或先取消其中一个。",
                    limit=self.config.max_concurrent_file_saves,
                ),
            )
            return
        default_name = basename(full_path)
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("另存为"),
            default_name,
            tr("所有文件 (*)"),
        )
        if not save_path:
            return
        worker = FileDownloadWorker(
            self.client,
            self.get_base_url(),
            full_path,
            save_path,
        )
        self._task_manager.start(
            TaskSpec(
                kind=TaskKind.FILE_DOWNLOAD,
                title=tr("保存文件：{name}", name=basename(full_path)),
                detail=save_path,
                dedup_key=f"file-download:{self.get_base_url()}:{full_path}:{save_path}",
            ),
            worker,
        )

    def on_file_save_finished(self, save_path: str) -> None:
        if not self._closing_after_task_cancel:
            self._status_controller.show_transient(
                tr("保存完成: {path}", path=save_path)
            )

    def on_file_save_cancelled(self) -> None:
        if not self._closing_after_task_cancel:
            self._status_controller.show_transient(tr("文件保存已中断"))

    def on_file_save_failed(self, error: TaskError) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, tr("保存失败"), error.message)
            self._status_controller.show_transient(tr("文件保存失败"))

    def save_current_directory_to_local(self) -> None:
        if self.is_task_active(self._directory_load_task_id):
            QMessageBox.information(
                self,
                tr("任务进行中"),
                tr("目录正在加载中，请稍后再保存。"),
            )
            return
        if self.is_task_active(self._directory_save_task_id):
            QMessageBox.information(
                self,
                tr("任务进行中"),
                tr("已存在保存任务，请先等待完成或中断。"),
            )
            return
        base_url = self.get_base_url()
        if not base_url:
            QMessageBox.warning(self, tr("参数错误"), tr("地址不能为空"))
            return
        target_dir = QFileDialog.getExistingDirectory(
            self,
            tr("选择本地保存目录"),
        )
        if not target_dir:
            return

        worker = SaveDirectoryWorker(
            self.client,
            base_url,
            self.current_dir,
            target_dir,
            self.config.page_limit,
            self.config.directory_download_workers,
        )
        self._directory_save_task_id = self._task_manager.start(
            TaskSpec(
                kind=TaskKind.DIRECTORY_DOWNLOAD,
                title=tr(
                    "保存目录：{name}",
                    name=basename(self.current_dir),
                ),
                detail=target_dir,
                dedup_key="directory-download",
            ),
            worker,
        )

    def on_save_finished(self, result: Dict[str, Any]) -> None:
        total_files = int(result.get("total_files", 0))
        downloaded_files = int(result.get("downloaded_files", 0))
        target_dir = str(result.get("target_dir", ""))
        self._status_controller.show_transient(
            tr(
                "保存完成: {downloaded}/{total}",
                downloaded=downloaded_files,
                total=total_files,
            )
        )
        if target_dir and not self._closing_after_task_cancel:
            try:
                open_path_in_file_explorer(target_dir)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    tr("提示"),
                    tr(
                        "保存完成，但自动打开目录失败:\n{error}",
                        error=e,
                    ),
                )

    def on_save_cancelled(self) -> None:
        if not self._closing_after_task_cancel:
            self._status_controller.show_transient(tr("保存已中断"))

    def on_save_failed(self, error: TaskError) -> None:
        if not self._closing_after_task_cancel:
            QMessageBox.critical(self, tr("保存失败"), error.message)
        self._status_controller.show_transient(tr("保存失败"))

    def on_save_thread_cleaned(self) -> None:
        self._directory_save_task_id = None

    def on_create_directory_thread_cleaned(self) -> None:
        self._create_directory_task_id = None
        self._create_directory_context = None

    def on_upload_thread_cleaned(self) -> None:
        self._upload_task_id = None
        self._upload_context = None
        retry = self._pending_upload_retry
        self._pending_upload_retry = None
        if retry is None or self._closing_after_task_cancel:
            return
        base_url, target_dir, local_paths = retry
        try:
            items = build_upload_items(local_paths, target_dir, join_remote_child)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("无法重试上传"), str(error))
            return
        if items:
            QTimer.singleShot(
                0,
                lambda: self.start_upload_batch(items, base_url, target_dir),
            )

    def preview_key_for_task(self, task_id: str) -> Optional[str]:
        for preview_key, preview_task_id in self._preview_load_tasks.items():
            if preview_task_id == task_id:
                return preview_key
        return None

    def on_task_succeeded(self, task_id: str, result: Any) -> None:
        if task_id == self._directory_load_task_id:
            self.on_directory_load_finished(result)
            return
        if task_id == self._directory_save_task_id:
            self.on_save_finished(result)
            return
        if task_id == self._create_directory_task_id:
            self.on_create_directory_finished(result)
            return
        if task_id == self._upload_task_id:
            self.on_upload_finished(result)
            return
        preview_key = self.preview_key_for_task(task_id)
        if preview_key is not None:
            self.on_preview_load_finished(preview_key, result)
            return
        snapshot = self._task_manager.get(task_id)
        if snapshot is not None and snapshot.spec.kind == TaskKind.FILE_DOWNLOAD:
            self.on_file_save_finished(str(result))

    def on_task_failed(self, task_id: str, error: TaskError) -> None:
        if task_id == self._directory_load_task_id:
            self.on_directory_load_failed(error)
            return
        if task_id == self._directory_save_task_id:
            self.on_save_failed(error)
            return
        if task_id == self._create_directory_task_id:
            if self._create_directory_context is not None:
                self.on_create_directory_failed(
                    *self._create_directory_context,
                    error,
                )
            return
        if task_id == self._upload_task_id:
            if self._upload_context is not None:
                self.on_upload_failed(*self._upload_context, error)
            return
        preview_key = self.preview_key_for_task(task_id)
        if preview_key is not None:
            self.on_preview_load_failed(preview_key, error)
            return
        snapshot = self._task_manager.get(task_id)
        if snapshot is not None and snapshot.spec.kind == TaskKind.FILE_DOWNLOAD:
            self.on_file_save_failed(error)

    def on_task_cancelled(self, task_id: str) -> None:
        if task_id == self._directory_load_task_id:
            self.on_directory_load_cancelled()
            return
        if task_id == self._directory_save_task_id:
            self.on_save_cancelled()
            return
        if task_id == self._create_directory_task_id:
            if self._create_directory_context is not None:
                self.on_create_directory_cancelled(*self._create_directory_context)
            return
        if task_id == self._upload_task_id:
            if self._upload_context is not None:
                self.on_upload_cancelled(*self._upload_context)
            return
        preview_key = self.preview_key_for_task(task_id)
        if preview_key is not None:
            self.on_preview_load_cancelled(preview_key)
            return
        snapshot = self._task_manager.get(task_id)
        if snapshot is not None and snapshot.spec.kind == TaskKind.FILE_DOWNLOAD:
            self.on_file_save_cancelled()

    def on_task_cleaned(self, task_id: str) -> None:
        if task_id == self._directory_load_task_id:
            self.on_directory_load_thread_cleaned()
            return
        if task_id == self._directory_save_task_id:
            self.on_save_thread_cleaned()
            return
        if task_id == self._create_directory_task_id:
            self.on_create_directory_thread_cleaned()
            return
        if task_id == self._upload_task_id:
            self.on_upload_thread_cleaned()
            return
        for preview_key, preview_task_id in list(self._preview_load_tasks.items()):
            if task_id == preview_task_id:
                self.on_preview_load_thread_cleaned(preview_key)
                return

    def on_all_tasks_finished(self) -> None:
        if self._closing_after_task_cancel:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event) -> None:
        for window in list(self._preview_windows.values()):
            window.close()

        if self._task_manager.has_active_tasks():
            self._closing_after_task_cancel = True
            self.setEnabled(False)
            self._status_controller.show_transient(
                tr("正在取消后台任务并清理临时资源..."),
                timeout_ms=0,
            )
            self._task_manager.cancel_all()
            event.ignore()
            return

        self._model_process_timer.stop()
        self.terminate_model_preview_processes()
        super().closeEvent(event)


def main() -> int:
    set_language(load_config().language)
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
