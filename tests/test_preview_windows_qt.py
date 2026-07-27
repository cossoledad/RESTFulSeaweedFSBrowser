import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget

    from seaweed_browser.widgets import PreviewDialog
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 is not installed in the lightweight test environment")
class PreviewWindowQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_text_preview_is_an_independent_taskbar_window(self) -> None:
        main_window = QWidget()
        preview = PreviewDialog("Preview", "content", parent=main_window)
        try:
            self.assertIsNone(preview.parentWidget())
            self.assertTrue(preview.isWindow())
            window_type = preview.windowFlags() & Qt.WindowType.WindowType_Mask
            self.assertEqual(window_type, Qt.WindowType.Window)
            self.assertFalse(preview.windowIcon().isNull())
        finally:
            preview.close()
            main_window.close()


if __name__ == "__main__":
    unittest.main()
