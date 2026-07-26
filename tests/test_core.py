import os
import tempfile
import unittest
from unittest.mock import patch

from seaweed_browser.core import (
    AppConfig,
    get_config_path,
    join_url,
    join_remote_child,
    load_config,
    remote_path_is_within_root,
    safe_local_path,
    sanitize_bounded_int,
    save_config,
    validate_remote_child_name,
)


class CoreTests(unittest.TestCase):
    def test_join_url_encodes_remote_path(self) -> None:
        self.assertEqual(
            join_url("http://localhost:8888/", "/bucket/中文 文件#1?.txt"),
            "http://localhost:8888/bucket/%E4%B8%AD%E6%96%87%20%E6%96%87%E4%BB%B6%231%3F.txt",
        )
        self.assertEqual(
            join_url("http://localhost:8888", "/bucket/100%完成.txt"),
            "http://localhost:8888/bucket/100%25%E5%AE%8C%E6%88%90.txt",
        )

    def test_safe_local_path_accepts_child(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            target = safe_local_path(root, "nested/file.bin")
            expected = os.path.join(root, "nested", "file.bin")
            self.assertEqual(
                os.path.normcase(os.path.realpath(target)),
                os.path.normcase(os.path.realpath(expected)),
            )

    def test_remote_child_name_is_validated_and_joined(self) -> None:
        self.assertEqual(
            join_remote_child("/bucket/current/", "中文 文件.txt"),
            "/bucket/current/中文 文件.txt",
        )
        for invalid_name in ("", ".", "..", "../escape", "nested/file", "bad\\file", "bad\x00file"):
            with self.subTest(invalid_name=invalid_name):
                with self.assertRaises(ValueError):
                    validate_remote_child_name(invalid_name)

    def test_remote_path_must_remain_inside_configured_root(self) -> None:
        self.assertTrue(remote_path_is_within_root("/bucket/root", "/bucket/root/"))
        self.assertTrue(
            remote_path_is_within_root("/bucket/root/nested/file", "/bucket/root/")
        )
        self.assertFalse(
            remote_path_is_within_root("/bucket/root-other", "/bucket/root/")
        )
        self.assertFalse(
            remote_path_is_within_root("/bucket/root/../outside", "/bucket/root/")
        )

    def test_sanitize_bounded_int_uses_safe_range(self) -> None:
        self.assertEqual(sanitize_bounded_int(4, 2, 16), 4)
        self.assertEqual(sanitize_bounded_int(1000, 2, 16), 16)
        self.assertEqual(sanitize_bounded_int(0, 2, 16), 2)
        self.assertEqual(sanitize_bounded_int("invalid", 2, 16), 2)

    def test_safe_local_path_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            for relative_path in ("../escape.bin", "nested/../../escape.bin", "/absolute.bin"):
                with self.subTest(relative_path=relative_path):
                    with self.assertRaises(ValueError):
                        safe_local_path(root, relative_path)

    def test_safe_local_path_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = os.path.join(parent, "root")
            outside = os.path.join(parent, "outside")
            os.makedirs(root)
            os.makedirs(outside)
            link = os.path.join(root, "link")
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("当前平台不允许创建测试符号链接")
            with self.assertRaises(ValueError):
                safe_local_path(root, "link/escape.bin")

    def test_config_round_trip_uses_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}):
                config = AppConfig(
                    language="fr",
                    base_url="http://localhost:8888",
                    root_dir="/buckets/test/",
                    page_limit=250,
                    directory_cache_max_entries=8,
                    directory_download_workers=2,
                    upload_workers=5,
                    max_concurrent_preview_loads=2,
                    max_concurrent_file_saves=1,
                    base_url_history=["http://localhost:8888"],
                )
                save_config(config)
                self.assertTrue(os.path.exists(get_config_path()))
                loaded = load_config()
                self.assertEqual(loaded.language, "fr")
                self.assertEqual(loaded.base_url, config.base_url)
                self.assertEqual(loaded.root_dir, config.root_dir)
                self.assertEqual(loaded.page_limit, 250)
                self.assertEqual(loaded.directory_cache_max_entries, 8)
                self.assertEqual(loaded.directory_download_workers, 2)
                self.assertEqual(loaded.upload_workers, 5)
                self.assertEqual(loaded.max_concurrent_preview_loads, 2)
                self.assertEqual(loaded.max_concurrent_file_saves, 1)


if __name__ == "__main__":
    unittest.main()
