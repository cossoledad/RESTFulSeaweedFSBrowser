import os
import tempfile
import threading
import time
import unittest

from seaweed_browser.client import OperationCancelled
from seaweed_browser.core import join_remote_child
from seaweed_browser.uploads import (
    UploadItem,
    build_upload_items,
    upload_files_concurrently,
)


class RecordingUploadClient:
    def __init__(self, fail_names=None):
        self.fail_names = set(fail_names or [])
        self.active = 0
        self.max_active = 0
        self.completed = []
        self.lock = threading.Lock()

    def upload_file(
        self,
        base_url,
        remote_path,
        local_path,
        cancel_check=None,
        on_progress=None,
    ):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if cancel_check and cancel_check():
                raise OperationCancelled()
            size = os.path.getsize(local_path)
            if on_progress:
                on_progress(size, size)
            time.sleep(0.01)
            if remote_path in self.fail_names:
                raise RuntimeError("simulated failure")
            with self.lock:
                self.completed.append(remote_path)
        finally:
            with self.lock:
                self.active -= 1


class ConcurrentUploadTests(unittest.TestCase):
    def make_items(self, root: str, count: int):
        paths = []
        for index in range(count):
            path = os.path.join(root, f"{index}.bin")
            with open(path, "wb") as file:
                file.write(bytes([index]) * 10)
            paths.append(path)
        return build_upload_items(paths, "/target", join_remote_child)

    def test_limits_parallelism_and_continues_after_item_failure(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            items = self.make_items(root, 5)
            failed_path = items[2].remote_path
            client = RecordingUploadClient({failed_path})
            progress = []
            result = upload_files_concurrently(
                client,
                "http://localhost",
                items,
                max_workers=2,
                on_progress=lambda *values: progress.append(values),
            )

        self.assertLessEqual(client.max_active, 2)
        self.assertEqual(result.total_files, 5)
        self.assertEqual(result.uploaded_files, 4)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].item.remote_path, failed_path)
        self.assertTrue(progress)

    def test_build_items_rejects_duplicate_remote_names(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            first_dir = os.path.join(root, "first")
            second_dir = os.path.join(root, "second")
            os.makedirs(first_dir)
            os.makedirs(second_dir)
            first = os.path.join(first_dir, "same.bin")
            second = os.path.join(second_dir, "same.bin")
            open(first, "wb").close()
            open(second, "wb").close()
            with self.assertRaises(ValueError):
                build_upload_items([first, second], "/target", join_remote_child)

    def test_rejects_non_positive_worker_count(self) -> None:
        item = UploadItem("local", "/remote", 0)
        with self.assertRaises(ValueError):
            upload_files_concurrently(
                RecordingUploadClient(),
                "http://localhost",
                [item],
                max_workers=0,
            )


if __name__ == "__main__":
    unittest.main()
