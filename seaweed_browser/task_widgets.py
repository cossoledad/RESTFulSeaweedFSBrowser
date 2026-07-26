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

from .i18n import tr
from .task_models import TaskSnapshot, TaskState
from .task_presenter import format_progress, format_task_state
from .task_runtime import TaskManager


class TaskCenterDock(QDockWidget):
    def __init__(
        self,
        manager: TaskManager,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(tr("任务中心"), parent)
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
        self.clear_button = QPushButton(tr("清除已完成"))
        self.clear_button.clicked.connect(manager.clear_completed)
        toolbar.addWidget(self.clear_button)
        layout.addLayout(toolbar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(
            [tr("任务"), tr("状态"), tr("进度"), tr("详情"), tr("操作")]
        )
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

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("任务中心"))
        self.clear_button.setText(tr("清除已完成"))
        self.tree.setHeaderLabels(
            [tr("任务"), tr("状态"), tr("进度"), tr("详情"), tr("操作")]
        )
        self.rebuild()

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
                format_task_state(snapshot.state),
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
            cancel_button = QPushButton(tr("取消"))
            cancel_button.clicked.connect(
                lambda _checked=False, task_id=snapshot.task_id: self.manager.cancel(
                    task_id
                )
            )
            self.tree.setItemWidget(item, 4, cancel_button)
