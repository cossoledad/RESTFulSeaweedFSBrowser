import threading
import time
import unittest

from seaweed_browser.client import OperationCancelled
from seaweed_browser.downloads import DownloadItem, download_files_concurrently


class RecordingClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.completed = []

    def download_file_to_local(
        self,
        base_url,
        full_path,
        local_file_path,
        cancel_check=None,
    ) -> None:
        del base_url, local_file_path
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            for _ in range(4):
                if cancel_check is not None and cancel_check():
                    raise OperationCancelled("操作已取消")
                time.sleep(0.005)
            with self._lock:
                self.completed.append(full_path)
        finally:
            with self._lock:
                self.active -= 1


class FailingClient(RecordingClient):
    def __init__(self) -> None:
        super().__init__()
        self.started = []

    def download_file_to_local(
        self,
        base_url,
        full_path,
        local_file_path,
        cancel_check=None,
    ) -> None:
        self.started.append(full_path)
        if full_path == "/remote/fail":
            raise RuntimeError("download failed")
        super().download_file_to_local(
            base_url,
            full_path,
            local_file_path,
            cancel_check=cancel_check,
        )


class ConcurrentDownloadTests(unittest.TestCase):
    def test_limits_parallelism_and_reports_progress(self) -> None:
        client = RecordingClient()
        items = [
            DownloadItem(f"/remote/{index}", f"/local/{index}")
            for index in range(7)
        ]
        progress = []

        completed = download_files_concurrently(
            client,
            "http://localhost",
            items,
            max_workers=3,
            on_progress=lambda done, total, path: progress.append(
                (done, total, path)
            ),
        )

        self.assertEqual(completed, 7)
        self.assertEqual(client.max_active, 3)
        self.assertEqual([item[0] for item in progress], list(range(1, 8)))
        self.assertTrue(all(item[1] == 7 for item in progress))
        self.assertCountEqual(
            [item[2] for item in progress],
            [item.remote_path for item in items],
        )

    def test_cancellation_stops_batch(self) -> None:
        client = RecordingClient()
        cancelled = threading.Event()
        timer = threading.Timer(0.02, cancelled.set)
        timer.start()
        try:
            with self.assertRaises(OperationCancelled):
                download_files_concurrently(
                    client,
                    "http://localhost",
                    [
                        DownloadItem(f"/remote/{index}", f"/local/{index}")
                        for index in range(20)
                    ],
                    max_workers=2,
                    cancel_check=cancelled.is_set,
                )
        finally:
            timer.cancel()

        self.assertLess(len(client.completed), 20)
        self.assertEqual(client.active, 0)

    def test_failure_stops_submitting_new_items(self) -> None:
        client = FailingClient()
        with self.assertRaisesRegex(RuntimeError, "download failed"):
            download_files_concurrently(
                client,
                "http://localhost",
                [
                    DownloadItem("/remote/fail", "/local/fail"),
                    *[
                        DownloadItem(f"/remote/{index}", f"/local/{index}")
                        for index in range(10)
                    ],
                ],
                max_workers=2,
            )

        self.assertLessEqual(len(client.started), 2)
        self.assertEqual(client.active, 0)

    def test_rejects_non_positive_worker_count(self) -> None:
        with self.assertRaises(ValueError):
            download_files_concurrently(
                RecordingClient(),
                "http://localhost",
                [],
                max_workers=0,
            )


if __name__ == "__main__":
    unittest.main()
