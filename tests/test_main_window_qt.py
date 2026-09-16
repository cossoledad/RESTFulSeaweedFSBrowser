import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QApplication, QAbstractItemView

    from main import MainWindow
    from seaweed_browser.core import AppConfig, normalize_dir_path
    from seaweed_browser.widgets import MixedPathSelectionDialog

    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 is not installed in the lightweight test environment")
class MainWindowBehaviorQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self) -> MainWindow:
        class HarnessMainWindow(MainWindow):
            def load_directory(self, dir_path: str, force_reload: bool) -> bool:
                self.last_requested_directory = (dir_path, force_reload)
                self._directory_load_context = (
                    self.get_base_url(),
                    normalize_dir_path(dir_path),
                )
                return True

        config = AppConfig(
            base_url="http://old.example",
            root_dir="/bucket/root",
            location_history=[
                {"base_url": "http://old.example", "root_dir": "/bucket/root"},
                {"base_url": "http://old.example", "root_dir": "/other"},
            ],
        )
        with (
            patch("main.load_config", return_value=config),
            patch("main.save_config"),
        ):
            window = HarnessMainWindow()
        self.addCleanup(window.close)
        return window

    def test_editing_server_keeps_only_displayed_root_until_explicit_load(self) -> None:
        window = self.make_window()
        original_history = list(window.config.location_history)
        window.root_dir_input.setCurrentText("/visible/root")
        window.base_url_input.setCurrentText("http://new.example")

        window.on_base_url_edited("http://new.example")

        self.assertEqual(window.root_dir_input.count(), 0)
        self.assertEqual(window.root_dir_input.currentText(), "/visible/root")
        self.assertEqual(window.config.location_history, original_history)

        root_edit = window.root_dir_input.lineEdit()
        self.assertIsNotNone(root_edit)
        root_edit.setText("/edited/root")
        self.assertEqual(window.get_root_dir(), "/edited/root")

        with (
            patch.object(window, "start_directory_load"),
            patch("main.save_config"),
        ):
            MainWindow.load_directory(
                window,
                "/visible/root/child",
                force_reload=False,
            )
        self.assertEqual(window.config.location_history, original_history)

        window.root_dir_input.setCurrentText("/visible/root")
        with patch("main.save_config"):
            window.load_root_directory()
            self.assertEqual(window.config.location_history, original_history)
            self.assertEqual(
                window.last_requested_directory,
                ("/visible/root", True),
            )
            window.on_directory_load_finished([])
        self.assertEqual(
            window.config.location_history[0],
            {"base_url": "http://new.example", "root_dir": "/visible/root"},
        )

    def test_failed_explicit_root_load_is_not_saved_to_history(self) -> None:
        window = self.make_window()
        original_history = list(window.config.location_history)
        window.base_url_input.setCurrentText("http://unreachable.example")
        window.on_base_url_edited("http://unreachable.example")
        window.root_dir_input.setEditText("/new/root")

        window.load_root_directory()
        window.on_directory_load_cancelled()

        self.assertEqual(window.config.location_history, original_history)
        self.assertIsNone(window._pending_root_history)

    def test_up_from_root_moves_the_root_boundary(self) -> None:
        window = self.make_window()
        window.root_dir_input.setCurrentText("/bucket/root")
        window.current_dir = "/bucket/root"

        with (
            patch.object(window, "load_directory") as load_directory,
            patch("main.save_config"),
        ):
            window.go_up_directory()
            self.assertEqual(window.current_dir, "/bucket")
            self.assertEqual(window.get_root_dir(), "/bucket")
            load_directory.assert_called_once_with("/bucket", force_reload=False)

            load_directory.reset_mock()
            window.go_up_directory()
            self.assertEqual(window.current_dir, "/")
            self.assertEqual(window.get_root_dir(), "/")
            load_directory.assert_called_once_with("/", force_reload=False)

    def test_up_inside_root_does_not_change_root_boundary(self) -> None:
        window = self.make_window()
        window.root_dir_input.setCurrentText("/bucket/root")
        window.current_dir = "/bucket/root/child/grandchild"

        with patch.object(window, "load_directory"):
            window.go_up_directory()

        self.assertEqual(window.current_dir, "/bucket/root/child")
        self.assertEqual(window.get_root_dir(), "/bucket/root")

    def test_mixed_path_dialog_uses_extended_row_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = os.path.join(temp_dir, "folder")
            file_path = os.path.join(temp_dir, "file.txt")
            os.makedirs(folder)
            with open(file_path, "w", encoding="utf-8") as file:
                file.write("content")
            dialog = MixedPathSelectionDialog("Select", temp_dir)
            self.addCleanup(dialog.close)
            self.assertEqual(
                dialog.tree.selectionMode(),
                QAbstractItemView.SelectionMode.ExtendedSelection,
            )
            self.assertEqual(
                dialog.tree.selectionBehavior(),
                QAbstractItemView.SelectionBehavior.SelectRows,
            )
            self.app.processEvents()
            flags = (
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows
            )
            dialog.tree.selectionModel().select(dialog.model.index(folder), flags)
            dialog.tree.selectionModel().select(dialog.model.index(file_path), flags)
            dialog.accept_selection()
            self.assertEqual(
                {os.path.normcase(path) for path in dialog.selected_paths()},
                {os.path.normcase(folder), os.path.normcase(file_path)},
            )


if __name__ == "__main__":
    unittest.main()
