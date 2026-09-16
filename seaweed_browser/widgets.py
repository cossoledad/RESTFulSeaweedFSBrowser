import os
from typing import Callable, List, Optional

from PySide6.QtCore import QDir, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTreeView,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr
from .resources import get_app_window_icon


def configure_preview_window(dialog: QDialog) -> None:
    """Detach an owned preview so Windows gives it an independent taskbar item."""
    flags = dialog.windowFlags()
    flags = (flags & ~Qt.WindowType.WindowType_Mask) | Qt.WindowType.Window
    flags |= Qt.WindowType.WindowCloseButtonHint
    # Changing only WindowType_Mask does not remove the native owner created
    # from ``parent``.  An owned Windows window is deliberately omitted from
    # the taskbar, so detach it while MainWindow retains the Python reference.
    dialog.setParent(None, flags)
    dialog.setWindowIcon(get_app_window_icon())


class MixedPathSelectionDialog(QDialog):
    """Select any mixture of existing files and folders in one dialog."""

    def __init__(
        self,
        title: str,
        start_directory: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(get_app_window_icon())
        self.resize(920, 620)
        self._selected_paths: List[str] = []

        initial_directory = os.path.abspath(
            start_directory if os.path.isdir(start_directory) else QDir.homePath()
        )

        self.path_input = QLineEdit(self)
        self.path_input.setText(QDir.toNativeSeparators(initial_directory))
        self.path_input.returnPressed.connect(self.navigate_from_input)
        self.up_button = QPushButton(tr("上一级"), self)
        self.up_button.clicked.connect(self.navigate_up)
        self.computer_button = QPushButton(tr("此电脑"), self)
        self.computer_button.clicked.connect(self.show_computer)

        path_row = QHBoxLayout()
        path_row.addWidget(self.up_button)
        path_row.addWidget(self.computer_button)
        path_row.addWidget(self.path_input, 1)

        self.model = QFileSystemModel(self)
        self.model.setFilter(
            QDir.Filter.AllEntries
            | QDir.Filter.NoDotAndDotDot
            | QDir.Filter.AllDirs
            | QDir.Filter.Drives
        )
        self.model.setRootPath(initial_directory)

        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(initial_directory))
        self.tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setColumnWidth(0, 420)
        self.tree.doubleClicked.connect(self.handle_double_click)

        help_label = QLabel(
            tr("单击选择，双击文件夹进入；按 Ctrl 或 Shift 可同时选择多个文件和文件夹。"),
            self,
        )
        help_label.setWordWrap(True)

        buttons = QDialogButtonBox(self)
        self.select_button = buttons.addButton(
            tr("选择"),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        cancel_button = buttons.addButton(
            tr("取消"),
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.select_button.clicked.connect(self.accept_selection)
        cancel_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(path_row)
        layout.addWidget(self.tree, 1)
        layout.addWidget(help_label)
        layout.addWidget(buttons)

    def set_directory(self, directory: str) -> None:
        normalized = os.path.abspath(directory)
        if not os.path.isdir(normalized):
            return
        self.model.setRootPath(normalized)
        self.tree.setRootIndex(self.model.index(normalized))
        self.path_input.setText(QDir.toNativeSeparators(normalized))

    def navigate_from_input(self) -> None:
        path = QDir.fromNativeSeparators(self.path_input.text().strip())
        if path:
            self.set_directory(path)
        else:
            self.show_computer()

    def navigate_up(self) -> None:
        current = QDir.fromNativeSeparators(self.path_input.text().strip())
        if not current:
            return
        parent = os.path.dirname(os.path.abspath(current))
        if os.path.normcase(parent) == os.path.normcase(os.path.abspath(current)):
            self.show_computer()
        else:
            self.set_directory(parent)

    def show_computer(self) -> None:
        self.model.setRootPath("")
        self.tree.setRootIndex(QModelIndex())
        self.path_input.clear()

    def handle_double_click(self, index: QModelIndex) -> None:
        path = self.model.filePath(index)
        if os.path.isdir(path):
            self.set_directory(path)

    def accept_selection(self) -> None:
        rows = self.tree.selectionModel().selectedRows(0)
        paths: List[str] = []
        seen = set()
        for index in rows:
            path = os.path.abspath(self.model.filePath(index))
            if path in seen or not os.path.exists(path):
                continue
            seen.add(path)
            paths.append(path)
        if not paths:
            return
        self._selected_paths = paths
        self.accept()

    def selected_paths(self) -> List[str]:
        return list(self._selected_paths)


class SortableTreeWidgetItem(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        if tree is None:
            return super().__lt__(other)
        column = tree.sortColumn()
        left = self.data(column, Qt.ItemDataRole.UserRole + 1)
        right = other.data(column, Qt.ItemDataRole.UserRole + 1)
        if left is None or right is None:
            return super().__lt__(other)
        return left < right


class PreviewDialog(QDialog):
    def __init__(
        self,
        title: str,
        content: str,
        on_save_as: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        configure_preview_window(self)
        self.setWindowTitle(title)
        self.resize(900, 600)
        self._on_save_as = on_save_as

        text = QPlainTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(content)

        buttons = QDialogButtonBox(self)
        self.save_btn = buttons.addButton(
            tr("另存为本地文件"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        close_btn = buttons.addButton(
            tr("关闭"),
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.save_btn.setEnabled(on_save_as is not None)
        self.save_btn.clicked.connect(self.handle_save_as)
        close_btn.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(text)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def handle_save_as(self) -> None:
        if self._on_save_as is not None:
            self._on_save_as()


class ImagePreviewArea(QScrollArea):
    zoomChanged = Signal(float)

    def __init__(self, pixmap: QPixmap, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._original_pixmap = pixmap
        self._scale_factor = 1.0
        self._drag_active = False
        self._drag_start = QPoint()
        self._drag_h_value = 0
        self._drag_v_value = 0

        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setBackgroundRole(self.backgroundRole())
        self.setStyleSheet("QScrollArea { background: #111; border: 1px solid #444; }")

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.image_label)
        self.update_pixmap()

    @property
    def scale_factor(self) -> float:
        return self._scale_factor

    def reset_zoom(self) -> None:
        self._scale_factor = 1.0
        self.update_pixmap()
        self.zoomChanged.emit(self._scale_factor)

    def zoom_by(self, multiplier: float, anchor_pos=None) -> None:
        old_factor = self._scale_factor
        new_factor = max(0.05, min(8.0, old_factor * multiplier))
        if abs(new_factor - old_factor) < 1e-9:
            return
        self._scale_factor = new_factor
        self.update_pixmap()
        self.zoomChanged.emit(self._scale_factor)
        scale_change = new_factor / old_factor
        if anchor_pos is None:
            return
        h_bar = self.horizontalScrollBar()
        v_bar = self.verticalScrollBar()
        h_bar.setValue(int((h_bar.value() + anchor_pos.x()) * scale_change - anchor_pos.x()))
        v_bar.setValue(int((v_bar.value() + anchor_pos.y()) * scale_change - anchor_pos.y()))

    def update_pixmap(self) -> None:
        scaled = self._original_pixmap.scaled(
            max(1, int(self._original_pixmap.width() * self._scale_factor)),
            max(1, int(self._original_pixmap.height() * self._scale_factor)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.resize(scaled.size())

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        self.zoom_by(1.15 if delta > 0 else 1 / 1.15, event.position().toPoint())
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self._drag_start = event.position().toPoint()
            self._drag_h_value = self.horizontalScrollBar().value()
            self._drag_v_value = self.verticalScrollBar().value()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_active:
            delta = event.position().toPoint() - self._drag_start
            self.horizontalScrollBar().setValue(self._drag_h_value - delta.x())
            self.verticalScrollBar().setValue(self._drag_v_value - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_active:
            self._drag_active = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ImagePreviewDialog(QDialog):
    def __init__(
        self,
        title: str,
        image_path: str,
        on_save_as: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        configure_preview_window(self)
        self.setWindowTitle(title)
        self.resize(960, 720)
        self._on_save_as = on_save_as
        self._pixmap = QPixmap(image_path)
        if self._pixmap.isNull():
            raise RuntimeError(tr("无法加载图片"))

        self.info_label = QLabel()
        self.preview_area = ImagePreviewArea(self._pixmap, self)
        self.preview_area.zoomChanged.connect(self.on_zoom_changed)

        buttons = QDialogButtonBox(self)
        self.save_btn = buttons.addButton(
            tr("另存为本地文件"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.reset_btn = buttons.addButton(
            tr("重置缩放"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        close_btn = buttons.addButton(
            tr("关闭"),
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.save_btn.setEnabled(on_save_as is not None)
        self.save_btn.clicked.connect(self.handle_save_as)
        self.reset_btn.clicked.connect(self.handle_reset_zoom)
        close_btn.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(self.info_label)
        layout.addWidget(self.preview_area, 1)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self.update_info_label()

    def handle_save_as(self) -> None:
        if self._on_save_as is not None:
            self._on_save_as()

    def handle_reset_zoom(self) -> None:
        self.preview_area.reset_zoom()
        self.update_info_label()

    def update_info_label(self) -> None:
        zoom_percent = int(round(self.preview_area.scale_factor * 100))
        self.info_label.setText(
            f"{self._pixmap.width()} x {self._pixmap.height()} px | "
            + tr(
                "缩放 {percent}% | 滚轮缩放，左键拖拽，双击重置",
                percent=zoom_percent,
            )
        )

    def on_zoom_changed(self, _: float) -> None:
        self.update_info_label()


class EntryDetailDialog(QDialog):
    def __init__(self, title: str, details_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        configure_preview_window(self)
        self.setWindowTitle(title)
        self.resize(920, 680)

        text = QPlainTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(details_text)

        buttons = QDialogButtonBox(self)
        copy_btn = buttons.addButton(
            tr("复制全部"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        close_btn = buttons.addButton(
            tr("关闭"),
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(text.toPlainText())
        )
        close_btn.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(text)
        layout.addWidget(buttons)
        self.setLayout(layout)
