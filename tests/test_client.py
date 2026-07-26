import io
import base64
import hashlib
import json
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


class FakeHttpResponse:
    def __init__(
        self,
        payload: dict,
        status: int = 201,
        reason: str = "Created",
        headers=None,
    ):
        self.status = status
        self.reason = reason
        self._raw = json.dumps(payload).encode("utf-8")
        self._headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._raw

    def getheader(self, name: str, default: str = "") -> str:
        return self._headers.get(name, default)


class FakeHttpConnection:
    def __init__(self, response: FakeHttpResponse):
        self.response = response
        self.method = ""
        self.target = ""
        self.headers = {}
        self.sent = []
        self.closed = False

    def putrequest(self, method: str, target: str) -> None:
        self.method = method
        self.target = target

    def putheader(self, name: str, value: str) -> None:
        self.headers[name] = value

    def endheaders(self) -> None:
        pass

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def getresponse(self) -> FakeHttpResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class ClientTests(unittest.TestCase):
    def test_create_directory_uses_empty_post_without_content_type(self) -> None:
        connection = FakeHttpConnection(FakeHttpResponse({"name": "新目录"}))
        with patch(
            "seaweed_browser.client.open_http_connection",
            return_value=(connection, "/bucket/%E6%96%B0%E7%9B%AE%E5%BD%95/"),
        ):
            result = SeaweedClient().create_directory(
                "http://localhost:8888",
                "/bucket/新目录",
            )

        self.assertEqual(connection.method, "POST")
        self.assertTrue(connection.target.endswith("/"))
        self.assertEqual(connection.headers["Content-Length"], "0")
        self.assertNotIn("Content-Type", connection.headers)
        self.assertEqual(result["name"], "新目录")
        self.assertTrue(connection.closed)

    def test_upload_streams_put_and_verifies_response_md5(self) -> None:
        content = b"x" * 70000
        expected_md5 = base64.b64encode(hashlib.md5(content).digest()).decode("ascii")
        response = FakeHttpResponse(
            {"name": "file.bin", "size": len(content)},
            headers={"Content-MD5": expected_md5},
        )
        connection = FakeHttpConnection(response)
        progress = []
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "file.bin")
            with open(source, "wb") as file:
                file.write(content)
            with patch(
                "seaweed_browser.client.open_http_connection",
                return_value=(connection, "/bucket/file.bin"),
            ):
                result = SeaweedClient().upload_file(
                    "http://localhost:8888",
                    "/bucket/file.bin",
                    source,
                    on_progress=lambda sent, total: progress.append((sent, total)),
                )

        self.assertEqual(connection.method, "PUT")
        self.assertEqual(connection.headers["Content-Length"], str(len(content)))
        self.assertGreater(len(connection.sent), 1)
        self.assertEqual(b"".join(connection.sent), content)
        self.assertEqual(progress[-1], (len(content), len(content)))
        self.assertTrue(result["verified"])
        self.assertTrue(connection.closed)

    def test_cancelled_upload_closes_connection_before_response(self) -> None:
        connection = FakeHttpConnection(FakeHttpResponse({}))
        checks = 0

        def cancelled() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 3

        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "file.bin")
            with open(source, "wb") as file:
                file.write(b"x" * 200000)
            with patch(
                "seaweed_browser.client.open_http_connection",
                return_value=(connection, "/bucket/file.bin"),
            ):
                with self.assertRaises(OperationCancelled):
                    SeaweedClient().upload_file(
                        "http://localhost:8888",
                        "/bucket/file.bin",
                        source,
                        cancel_check=cancelled,
                    )
        self.assertTrue(connection.closed)
        self.assertLess(len(b"".join(connection.sent)), 200000)
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
