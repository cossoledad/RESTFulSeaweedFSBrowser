import io
import os
import tempfile
import unittest
from unittest.mock import patch

from seaweed_browser.client import OperationCancelled, SeaweedClient


class FakeResponse:
    def __init__(self, content: bytes):
        self._stream = io.BytesIO(content)
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


class ClientTests(unittest.TestCase):
    def test_atomic_download_replaces_target_only_after_success(self) -> None:
        client = SeaweedClient()
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "file.bin")
            with open(target, "wb") as f:
                f.write(b"old")
            with patch(
                "seaweed_browser.client.urllib.request.urlopen",
                return_value=FakeResponse(b"new-content"),
            ):
                client.download_file_to_local("http://localhost", "/file.bin", target)
            with open(target, "rb") as f:
                self.assertEqual(f.read(), b"new-content")
            self.assertFalse(any(".part-" in name for name in os.listdir(root)))

    def test_cancelled_download_preserves_existing_target(self) -> None:
        client = SeaweedClient()
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "file.bin")
            with open(target, "wb") as f:
                f.write(b"old")
            cancel_checks = 0

            def is_cancelled() -> bool:
                nonlocal cancel_checks
                cancel_checks += 1
                return cancel_checks >= 2

            with patch(
                "seaweed_browser.client.urllib.request.urlopen",
                return_value=FakeResponse(b"x" * 100),
            ):
                with self.assertRaises(OperationCancelled):
                    client.download_file_to_local(
                        "http://localhost",
                        "/file.bin",
                        target,
                        cancel_check=is_cancelled,
                    )
            with open(target, "rb") as f:
                self.assertEqual(f.read(), b"old")
            self.assertFalse(any(".part-" in name for name in os.listdir(root)))


if __name__ == "__main__":
    unittest.main()
