import unittest

from seaweed_browser.task_models import (
    ProgressMode,
    ProgressUnit,
    TaskKind,
    TaskProgress,
    TaskSnapshot,
    TaskSpec,
    TaskState,
    select_primary_task,
)


class TaskProgressTests(unittest.TestCase):
    def test_percent_is_clamped_and_requires_known_total(self) -> None:
        self.assertEqual(
            TaskProgress.determinate(120, 100, ProgressUnit.BYTES).percent(),
            100,
        )
        self.assertEqual(
            TaskProgress.determinate(-1, 100, ProgressUnit.ITEMS).percent(),
            0,
        )
        unknown = TaskProgress.determinate(1, 0, ProgressUnit.ITEMS)
        self.assertEqual(unknown.mode, ProgressMode.INDETERMINATE)
        self.assertIsNone(unknown.percent())


class PrimaryTaskSelectionTests(unittest.TestCase):
    @staticmethod
    def snapshot(
        task_id: str,
        kind: TaskKind,
        state: TaskState,
        *,
        priority: int = 0,
        started_at: float = 1.0,
    ) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=task_id,
            spec=TaskSpec(kind, task_id, priority=priority),
            state=state,
            progress=TaskProgress.indeterminate(),
            created_at=started_at,
            started_at=started_at,
        )

    def test_upload_has_priority_over_preview(self) -> None:
        preview = self.snapshot("preview", TaskKind.PREVIEW_LOAD, TaskState.RUNNING)
        upload = self.snapshot("upload", TaskKind.FILE_UPLOAD, TaskState.RUNNING)
        self.assertEqual(select_primary_task([preview, upload]), upload)

    def test_terminal_tasks_are_ignored(self) -> None:
        failed = self.snapshot("failed", TaskKind.FILE_UPLOAD, TaskState.FAILED)
        running = self.snapshot(
            "running",
            TaskKind.DIRECTORY_CREATE,
            TaskState.RUNNING,
        )
        self.assertEqual(select_primary_task([failed, running]), running)

    def test_explicit_priority_overrides_kind_default(self) -> None:
        upload = self.snapshot("upload", TaskKind.FILE_UPLOAD, TaskState.RUNNING)
        preview = self.snapshot(
            "preview",
            TaskKind.PREVIEW_LOAD,
            TaskState.RUNNING,
            priority=100,
        )
        self.assertEqual(select_primary_task([upload, preview]), preview)


if __name__ == "__main__":
    unittest.main()
