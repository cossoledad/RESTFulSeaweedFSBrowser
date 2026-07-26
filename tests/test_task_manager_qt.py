import time
import unittest

try:
    from PySide6.QtCore import QCoreApplication, QTimer, Signal

    from seaweed_browser.tasks import CancellableWorker, TaskManager

    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 is not installed in the lightweight test environment")
class TaskManagerQtTests(unittest.TestCase):
    def test_cancel_all_reaches_busy_worker_and_reaps_thread(self) -> None:
        class BusyWorker(CancellableWorker):
            finished = Signal()
            cancelled = Signal()
            error = Signal(str)

            def run(self) -> None:
                while not self.is_cancelled():
                    time.sleep(0.005)
                self.cancelled.emit()

        app = QCoreApplication.instance() or QCoreApplication([])
        manager = TaskManager()
        worker = BusyWorker()
        completed = []
        manager.all_finished.connect(lambda: (completed.append(True), app.quit()))
        manager.start("busy", worker, (worker.finished, worker.cancelled, worker.error))
        QTimer.singleShot(20, manager.cancel_all)
        QTimer.singleShot(2000, app.quit)
        app.exec()

        self.assertEqual(completed, [True])
        self.assertFalse(manager.has_active_tasks())
        self.assertTrue(worker.is_cancelled())


if __name__ == "__main__":
    unittest.main()
