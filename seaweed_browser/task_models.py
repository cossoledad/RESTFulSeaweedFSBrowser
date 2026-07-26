from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class TaskKind(Enum):
    DIRECTORY_LOAD = "directory_load"
    DIRECTORY_CREATE = "directory_create"
    FILE_UPLOAD = "file_upload"
    FILE_DOWNLOAD = "file_download"
    DIRECTORY_DOWNLOAD = "directory_download"
    PREVIEW_LOAD = "preview_load"


class TaskState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProgressMode(Enum):
    INDETERMINATE = "indeterminate"
    DETERMINATE = "determinate"


class ProgressUnit(Enum):
    NONE = "none"
    BYTES = "bytes"
    ITEMS = "items"
    ENTRIES = "entries"
    STEPS = "steps"


ACTIVE_TASK_STATES = {
    TaskState.QUEUED,
    TaskState.RUNNING,
    TaskState.CANCELLING,
}
TERMINAL_TASK_STATES = {
    TaskState.SUCCEEDED,
    TaskState.FAILED,
    TaskState.CANCELLED,
}


@dataclass(frozen=True)
class TaskProgress:
    mode: ProgressMode = ProgressMode.INDETERMINATE
    current: int = 0
    total: int = 0
    unit: ProgressUnit = ProgressUnit.NONE
    phase: str = ""
    detail: str = ""
    secondary_current: int = 0
    secondary_total: int = 0

    @classmethod
    def indeterminate(cls, phase: str = "", detail: str = "") -> "TaskProgress":
        return cls(phase=phase, detail=detail)

    @classmethod
    def determinate(
        cls,
        current: int,
        total: int,
        unit: ProgressUnit,
        phase: str = "",
        detail: str = "",
        secondary_current: int = 0,
        secondary_total: int = 0,
    ) -> "TaskProgress":
        return cls(
            mode=ProgressMode.DETERMINATE if total > 0 else ProgressMode.INDETERMINATE,
            current=max(0, current),
            total=max(0, total),
            unit=unit,
            phase=phase,
            detail=detail,
            secondary_current=max(0, secondary_current),
            secondary_total=max(0, secondary_total),
        )

    def percent(self) -> Optional[int]:
        if self.mode != ProgressMode.DETERMINATE or self.total <= 0:
            return None
        return min(100, max(0, int(self.current * 100 / self.total)))


@dataclass(frozen=True)
class TaskError:
    message: str
    detail: str = ""
    retryable: bool = False
    payload: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class TaskSpec:
    kind: TaskKind
    title: str
    detail: str = ""
    cancellable: bool = True
    dedup_key: Optional[str] = None
    priority: int = 0
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    spec: TaskSpec
    state: TaskState
    progress: TaskProgress
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[TaskError] = None

    @property
    def is_active(self) -> bool:
        return self.state in ACTIVE_TASK_STATES

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_TASK_STATES


TASK_KIND_PRIORITY = {
    TaskKind.FILE_UPLOAD: 60,
    TaskKind.FILE_DOWNLOAD: 55,
    TaskKind.DIRECTORY_DOWNLOAD: 50,
    TaskKind.DIRECTORY_LOAD: 40,
    TaskKind.PREVIEW_LOAD: 30,
    TaskKind.DIRECTORY_CREATE: 20,
}


def select_primary_task(snapshots: list[TaskSnapshot]) -> Optional[TaskSnapshot]:
    active = [snapshot for snapshot in snapshots if snapshot.is_active]
    if not active:
        return None
    return max(
        active,
        key=lambda snapshot: (
            snapshot.spec.priority or TASK_KIND_PRIORITY.get(snapshot.spec.kind, 0),
            snapshot.started_at or snapshot.created_at,
        ),
    )
