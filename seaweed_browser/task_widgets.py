from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .task_models import TaskSnapshot, TaskState
from .task_presenter import STATE_TEXT, format_progress
from .task_runtime import TaskManager


class TaskCenterDock(QDockWidget):
    def __init__(
        self,
        manager: TaskManager,
        parent: Optional[QWidget] = None,
    ):
        super().__init__("任务中心", parent)
        self.manager = manager
        self.setObjectName("TaskCenterDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        root = QWidget(self)
        layout = QVBoxLayout(root)
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        clear_button = QPushButton("清除已完成")
        clear_button.clicked.connect(manager.clear_completed)
        toolbar.addWidget(clear_button)
        layout.addLayout(toolbar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["任务", "状态", "进度", "详情", "操作"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 210)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 180)
        self.tree.setColumnWidth(3, 360)
        layout.addWidget(self.tree)
        self.setWidget(root)

        manager.task_added.connect(lambda _: self.rebuild())
        manager.task_updated.connect(lambda _: self.rebuild())
        manager.task_removed.connect(lambda _: self.rebuild())
        self.rebuild()

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()

    def rebuild(self) -> None:
        self.tree.clear()
        snapshots = sorted(
            self.manager.snapshots(),
            key=lambda snapshot: (
                0 if snapshot.is_active else 1,
                -(snapshot.started_at or snapshot.created_at),
            ),
        )
        for snapshot in snapshots:
            self._add_snapshot(snapshot)

    def _add_snapshot(self, snapshot: TaskSnapshot) -> None:
        detail = snapshot.progress.detail or snapshot.spec.detail
        if snapshot.error is not None:
            detail = snapshot.error.message
        item = QTreeWidgetItem(
            [
                snapshot.spec.title,
                STATE_TEXT[snapshot.state],
                format_progress(snapshot.progress),
                detail,
                "",
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, snapshot.task_id)
        if snapshot.error is not None:
            item.setToolTip(3, snapshot.error.detail or snapshot.error.message)
        self.tree.addTopLevelItem(item)

        if (
            snapshot.is_active
            and snapshot.spec.cancellable
            and snapshot.state != TaskState.CANCELLING
        ):
            cancel_button = QPushButton("取消")
            cancel_button.clicked.connect(
                lambda _checked=False, task_id=snapshot.task_id: self.manager.cancel(
                    task_id
                )
            )
            self.tree.setItemWidget(item, 4, cancel_button)
