import json
import os
import tempfile
import unittest

from seaweed_browser.cancellation import CancellationToken
from seaweed_browser.client import OperationCancelled
from seaweed_browser.model_files import collect_gltf_resource_paths


class ModelFileTests(unittest.TestCase):
    def test_collects_unique_safe_relative_resources(self) -> None:
        payload = {
            "buffers": [{"uri": "mesh.bin"}, {"uri": "mesh.bin"}],
            "images": [
                {"uri": "textures/diffuse%20map.png"},
                {"uri": "data:image/png;base64,AAAA"},
                {"uri": "https://example.com/external.png"},
            ],
        }
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "model.gltf")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            self.assertEqual(
                collect_gltf_resource_paths(path),
                ["mesh.bin", "textures/diffuse map.png"],
            )

    def test_rejects_parent_resource_path(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "model.gltf")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"buffers": [{"uri": "../secret.bin"}]}, f)
            with self.assertRaises(ValueError):
                collect_gltf_resource_paths(path)

    def test_cancellation_token_is_thread_safe_contract(self) -> None:
        token = CancellationToken()
        self.assertFalse(token.is_cancelled())
        token.cancel()
        self.assertTrue(token.is_cancelled())
        with self.assertRaises(OperationCancelled):
            token.raise_if_cancelled()


if __name__ == "__main__":
    unittest.main()
