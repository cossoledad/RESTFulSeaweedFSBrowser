import time
import unittest

try:
    from PySide6.QtCore import QCoreApplication, QTimer

    from seaweed_browser.task_models import (
        TaskError,
        TaskKind,
        TaskSpec,
        TaskState,
    )
    from seaweed_browser.task_runtime import TaskManager
    from seaweed_browser.tasks import CancellableWorker

    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 is not installed in the lightweight test environment")
class TaskManagerQtTests(unittest.TestCase):
    def test_cancel_all_reaches_busy_worker_and_reaps_thread(self) -> None:
        class BusyWorker(CancellableWorker):
            def run(self) -> None:
                while not self.is_cancelled():
                    time.sleep(0.005)
                self.cancelled.emit()

        app = QCoreApplication.instance() or QCoreApplication([])
        manager = TaskManager()
        worker = BusyWorker()
        completed = []
        manager.all_finished.connect(lambda: (completed.append(True), app.quit()))
        task_id = manager.start(
            TaskSpec(TaskKind.FILE_DOWNLOAD, "繁忙任务"),
            worker,
        )
        self.assertEqual(manager.count(), 1)
        self.assertEqual(manager.count(TaskKind.FILE_DOWNLOAD), 1)
        self.assertEqual(manager.count(TaskKind.PREVIEW_LOAD), 0)
        QTimer.singleShot(20, manager.cancel_all)
        QTimer.singleShot(2000, app.quit)
        app.exec()

        self.assertEqual(completed, [True])
        self.assertFalse(manager.has_active_tasks())
        self.assertEqual(manager.count(), 0)
        snapshot = manager.get(task_id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.state, TaskState.CANCELLED)

    def test_success_is_kept_in_history_and_result_is_forwarded(self) -> None:
        class SuccessfulWorker(CancellableWorker):
            def run(self) -> None:
                self.succeeded.emit({"large_business_result": [1, 2, 3]})

        app = QCoreApplication.instance() or QCoreApplication([])
        manager = TaskManager(history_limit=1)
        finished = []
        results = []
        manager.task_succeeded.connect(
            lambda current_id, result: results.append((current_id, result))
        )
        manager.all_finished.connect(lambda: (finished.append(True), app.quit()))
        task_id = manager.start(
            TaskSpec(TaskKind.DIRECTORY_LOAD, "加载目录"),
            SuccessfulWorker(),
        )
        QTimer.singleShot(2000, app.quit)
        app.exec()

        self.assertEqual(finished, [True])
        snapshot = manager.get(task_id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.state, TaskState.SUCCEEDED)
        self.assertIsNone(snapshot.error)
        self.assertEqual(
            results,
            [(task_id, {"large_business_result": [1, 2, 3]})],
        )

    def test_failure_history_does_not_retain_business_payload(self) -> None:
        class FailedWorker(CancellableWorker):
            def run(self) -> None:
                self.failed.emit(
                    TaskError(
                        "部分失败",
                        retryable=True,
                        payload={"failed_items": ["a", "b"]},
                    )
                )

        app = QCoreApplication.instance() or QCoreApplication([])
        manager = TaskManager()
        failures = []
        manager.task_failed.connect(
            lambda current_id, error: failures.append((current_id, error))
        )
        manager.all_finished.connect(app.quit)
        task_id = manager.start(
            TaskSpec(TaskKind.FILE_UPLOAD, "上传文件"),
            FailedWorker(),
        )
        QTimer.singleShot(2000, app.quit)
        app.exec()

        snapshot = manager.get(task_id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.state, TaskState.FAILED)
        self.assertIsNotNone(snapshot.error)
        self.assertTrue(snapshot.error.retryable)
        self.assertIsNone(snapshot.error.payload)
        self.assertEqual(
            failures[0][1].payload,
            {"failed_items": ["a", "b"]},
        )


if __name__ == "__main__":
    unittest.main()
