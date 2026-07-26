from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QStatusBar

from .core import format_size
from .task_models import (
    ProgressMode,
    ProgressUnit,
    TaskProgress,
    TaskSnapshot,
    TaskState,
    select_primary_task,
)
from .task_runtime import TaskManager


STATE_TEXT = {
    TaskState.QUEUED: "等待中",
    TaskState.RUNNING: "运行中",
    TaskState.CANCELLING: "正在取消",
    TaskState.SUCCEEDED: "已完成",
    TaskState.FAILED: "失败",
    TaskState.CANCELLED: "已取消",
}


def format_progress(progress: TaskProgress) -> str:
    if progress.mode == ProgressMode.INDETERMINATE:
        return progress.phase or "处理中"
    if progress.unit == ProgressUnit.BYTES:
        value = f"{format_size(progress.current)} / {format_size(progress.total)}"
    else:
        value = f"{progress.current}/{progress.total}"
    percent = progress.percent()
    prefix = f"{progress.phase} · " if progress.phase else ""
    suffix = f" · {percent}%" if percent is not None else ""
    return f"{prefix}{value}{suffix}"


def format_task_summary(snapshot: TaskSnapshot) -> str:
    if snapshot.state == TaskState.CANCELLING:
        return f"正在取消：{snapshot.spec.title}"
    text = snapshot.spec.title
    progress_text = format_progress(snapshot.progress)
    if progress_text:
        text = f"{text} · {progress_text}"
    return text


class TaskStatusController(QObject):
    def __init__(
        self,
        manager: TaskManager,
        status_bar: QStatusBar,
        on_show_tasks: Callable[[], None],
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.manager = manager
        self.status_bar = status_bar
        self._transient_message = "就绪"
        self._transient_timer = QTimer(self)
        self._transient_timer.setSingleShot(True)
        self._transient_timer.timeout.connect(self._clear_transient)

        self.label = QLabel("就绪")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(150)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.tasks_button = QPushButton("任务")
        self.tasks_button.clicked.connect(on_show_tasks)
        self.tasks_button.hide()
        status_bar.addWidget(self.label, 1)
        status_bar.addPermanentWidget(self.progress)
        status_bar.addPermanentWidget(self.tasks_button)

        manager.task_added.connect(lambda _: self.refresh())
        manager.task_updated.connect(lambda _: self.refresh())
        manager.task_removed.connect(lambda _: self.refresh())

    def show_transient(self, message: str, timeout_ms: int = 5000) -> None:
        self._transient_message = message
        if timeout_ms > 0:
            self._transient_timer.start(timeout_ms)
        else:
            self._transient_timer.stop()
        self.refresh()

    def _clear_transient(self) -> None:
        self._transient_message = "就绪"
        self.refresh()

    def refresh(self) -> None:
        active = self.manager.active_snapshots()
        primary = select_primary_task(active)
        failed_count = sum(
            snapshot.state == TaskState.FAILED for snapshot in self.manager.snapshots()
        )
        if primary is None:
            self.progress.hide()
            self.label.setText(
                f"{failed_count} 个任务失败，点击查看"
                if failed_count
                else self._transient_message
            )
        else:
            summary = format_task_summary(primary)
            if len(active) > 1:
                summary = f"{len(active)} 个后台任务 · {summary}"
            self.label.setText(summary)
            percent = primary.progress.percent()
            if percent is None:
                self.progress.setRange(0, 0)
            else:
                self.progress.setRange(0, 100)
                self.progress.setValue(percent)
            self.progress.show()
        task_count = len(active)
        history_count = len(self.manager.snapshots())
        self.tasks_button.setText(f"任务 ({task_count})")
        self.tasks_button.setVisible(bool(history_count))
