import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .task_models import (
    ACTIVE_TASK_STATES,
    TERMINAL_TASK_STATES,
    TaskError,
    TaskKind,
    TaskProgress,
    TaskSnapshot,
    TaskSpec,
    TaskState,
)


@dataclass
class ManagedTask:
    snapshot: TaskSnapshot
    thread: QThread
    worker: QObject
    relay: "TaskLifecycleRelay"


class TaskLifecycleRelay(QObject):
    def __init__(self, manager: "TaskManager", task_id: str):
        super().__init__(manager)
        self.manager = manager
        self.task_id = task_id

    @Slot(object)
    def on_progress(self, progress: TaskProgress) -> None:
        self.manager._on_progress(self.task_id, progress)

    @Slot(object)
    def on_succeeded(self, result: object) -> None:
        self.manager._set_terminal(self.task_id, TaskState.SUCCEEDED)
        self.manager.task_succeeded.emit(self.task_id, result)

    @Slot(object)
    def on_failed(self, error: object) -> None:
        task_error = (
            error if isinstance(error, TaskError) else TaskError(str(error))
        )
        self.manager._set_terminal(
            self.task_id,
            TaskState.FAILED,
            TaskError(
                task_error.message,
                task_error.detail,
                task_error.retryable,
            ),
        )
        self.manager.task_failed.emit(self.task_id, task_error)

    @Slot()
    def on_cancelled(self) -> None:
        self.manager._set_terminal(self.task_id, TaskState.CANCELLED)
        self.manager.task_cancelled.emit(self.task_id)


class TaskManager(QObject):
    task_added = Signal(object)
    task_updated = Signal(object)
    task_removed = Signal(str)
    task_cleaned = Signal(str)
    task_succeeded = Signal(str, object)
    task_failed = Signal(str, object)
    task_cancelled = Signal(str)
    all_finished = Signal()

    def __init__(
        self,
        parent: Optional[QObject] = None,
        history_limit: int = 50,
        kind_limits: Optional[Dict[TaskKind, int]] = None,
    ):
        super().__init__(parent)
        self.history_limit = max(1, history_limit)
        self.kind_limits = dict(kind_limits or {})
        self._tasks: Dict[str, ManagedTask] = {}
        self._snapshots: "OrderedDict[str, TaskSnapshot]" = OrderedDict()

    def start(self, spec: TaskSpec, worker: QObject) -> str:
        if spec.dedup_key and self.find_active_by_dedup_key(spec.dedup_key):
            raise RuntimeError(f"任务已经存在: {spec.dedup_key}")
        limit = self.kind_limits.get(spec.kind)
        if limit is not None and self.count(spec.kind) >= limit:
            raise RuntimeError(f"{spec.title}任务已达到并发上限 {limit}")

        task_id = uuid.uuid4().hex
        now = time.time()
        snapshot = TaskSnapshot(
            task_id=task_id,
            spec=spec,
            state=TaskState.QUEUED,
            progress=TaskProgress.indeterminate(),
            created_at=now,
        )
        thread = QThread(self)
        relay = TaskLifecycleRelay(self, task_id)
        worker.moveToThread(thread)
        managed = ManagedTask(
            snapshot=snapshot,
            thread=thread,
            worker=worker,
            relay=relay,
        )
        self._tasks[task_id] = managed
        self._snapshots[task_id] = snapshot
        self.task_added.emit(snapshot)

        worker.progress_changed.connect(relay.on_progress)
        worker.succeeded.connect(relay.on_succeeded)
        worker.failed.connect(relay.on_failed)
        worker.cancelled.connect(relay.on_cancelled)
        for signal in (worker.succeeded, worker.failed, worker.cancelled):
            signal.connect(thread.quit)

        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda current_id=task_id: self._on_thread_finished(current_id)
        )
        self._set_running(task_id)
        thread.start()
        return task_id

    def _set_running(self, task_id: str) -> None:
        snapshot = self.get(task_id)
        if snapshot is None or snapshot.state != TaskState.QUEUED:
            return
        self._replace_snapshot(
            replace(snapshot, state=TaskState.RUNNING, started_at=time.time())
        )

    def _on_progress(self, task_id: str, progress: TaskProgress) -> None:
        snapshot = self.get(task_id)
        if snapshot is None or snapshot.state not in ACTIVE_TASK_STATES:
            return
        if not isinstance(progress, TaskProgress):
            return
        self._replace_snapshot(replace(snapshot, progress=progress))

    def _set_terminal(
        self,
        task_id: str,
        state: TaskState,
        error: Optional[TaskError] = None,
    ) -> None:
        if state not in TERMINAL_TASK_STATES:
            raise ValueError(f"非法终态: {state}")
        snapshot = self.get(task_id)
        if snapshot is None or snapshot.state in TERMINAL_TASK_STATES:
            return
        progress = snapshot.progress
        if state == TaskState.SUCCEEDED and progress.total > 0:
            progress = replace(
                progress,
                current=progress.total,
                secondary_current=progress.secondary_total,
            )
        self._replace_snapshot(
            replace(
                snapshot,
                state=state,
                progress=progress,
                finished_at=time.time(),
                error=error,
            )
        )

    def _replace_snapshot(self, snapshot: TaskSnapshot) -> None:
        self._snapshots[snapshot.task_id] = snapshot
        managed = self._tasks.get(snapshot.task_id)
        if managed is not None:
            managed.snapshot = snapshot
        self.task_updated.emit(snapshot)

    def _on_thread_finished(self, task_id: str) -> None:
        snapshot = self.get(task_id)
        if snapshot is not None and snapshot.state not in TERMINAL_TASK_STATES:
            self._set_terminal(
                task_id,
                TaskState.FAILED,
                TaskError("后台线程意外退出"),
            )
        self._tasks.pop(task_id, None)
        self.task_cleaned.emit(task_id)
        self._trim_history()
        if not self._tasks:
            self.all_finished.emit()

    def _trim_history(self) -> None:
        terminal_ids = [
            task_id
            for task_id, snapshot in self._snapshots.items()
            if snapshot.is_terminal and task_id not in self._tasks
        ]
        while len(terminal_ids) > self.history_limit:
            task_id = terminal_ids.pop(0)
            self._snapshots.pop(task_id, None)
            self.task_removed.emit(task_id)

    def get(self, task_id: str) -> Optional[TaskSnapshot]:
        return self._snapshots.get(task_id)

    def snapshots(self) -> List[TaskSnapshot]:
        return list(self._snapshots.values())

    def active_snapshots(self) -> List[TaskSnapshot]:
        return [snapshot for snapshot in self._snapshots.values() if snapshot.is_active]

    def contains(self, task_id: str) -> bool:
        return task_id in self._tasks

    def find_active_by_dedup_key(self, dedup_key: str) -> Optional[TaskSnapshot]:
        for snapshot in self.active_snapshots():
            if snapshot.spec.dedup_key == dedup_key:
                return snapshot
        return None

    def count(self, kind: Optional[TaskKind] = None) -> int:
        snapshots = self.active_snapshots()
        if kind is None:
            return len(snapshots)
        return sum(snapshot.spec.kind == kind for snapshot in snapshots)

    def has_active_tasks(self) -> bool:
        return bool(self._tasks)

    def cancel(self, task_id: str) -> None:
        managed = self._tasks.get(task_id)
        if managed is None:
            return
        snapshot = managed.snapshot
        if snapshot.state not in {TaskState.QUEUED, TaskState.RUNNING}:
            return
        if not snapshot.spec.cancellable:
            return
        self._replace_snapshot(replace(snapshot, state=TaskState.CANCELLING))
        managed.worker.request_cancel()

    def cancel_all(self) -> None:
        for task_id in list(self._tasks):
            self.cancel(task_id)

    def clear_completed(self) -> None:
        for task_id, snapshot in list(self._snapshots.items()):
            if snapshot.is_terminal and task_id not in self._tasks:
                self._snapshots.pop(task_id, None)
                self.task_removed.emit(task_id)
