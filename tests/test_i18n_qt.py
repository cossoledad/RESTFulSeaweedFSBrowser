import unittest
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication

    from main import MainWindow
    from seaweed_browser.core import AppConfig

    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 is not installed in the lightweight test environment")
class I18nQtTests(unittest.TestCase):
    def test_main_window_retranslates_and_persists_language(self) -> None:
        app = QApplication.instance() or QApplication([])
        config = AppConfig(language="zh_CN")
        with (
            patch("main.load_config", return_value=config),
            patch("main.save_config") as save_config_mock,
            patch.object(MainWindow, "load_directory"),
        ):
            window = MainWindow()

            window.change_language("en")
            self.assertEqual(window.windowTitle(), "SeaweedFS Browser")
            self.assertEqual(window.create_dir_btn.text(), "New Folder")
            self.assertEqual(window.tree.headerItem().text(0), "Name")
            self.assertEqual(window._task_center.windowTitle(), "Task Center")
            self.assertEqual(config.language, "en")

            window.change_language("fr")
            self.assertEqual(window.windowTitle(), "Navigateur SeaweedFS")
            self.assertEqual(window.create_dir_btn.text(), "Nouveau dossier")
            self.assertEqual(window.tree.headerItem().text(0), "Nom")
            self.assertEqual(window._task_center.windowTitle(), "Centre des tâches")
            self.assertEqual(config.language, "fr")
            self.assertGreaterEqual(save_config_mock.call_count, 2)

            window.close()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
