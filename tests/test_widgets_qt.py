import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QWidget

    from seaweed_browser.widgets import (
        EntryDetailDialog,
        ImagePreviewDialog,
        PreviewDialog,
    )

    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 is not installed in the lightweight test environment")
class PreviewWindowQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def assert_is_taskbar_window(self, window) -> None:
        base_type = window.windowFlags() & Qt.WindowType.WindowType_Mask
        self.assertEqual(base_type, Qt.WindowType.Window)
        self.assertFalse(window.windowIcon().isNull())

    def test_text_preview_is_a_top_level_window(self) -> None:
        parent = QWidget()
        dialog = PreviewDialog("Text", "content", parent=parent)
        self.assert_is_taskbar_window(dialog)

    def test_image_preview_is_a_top_level_window(self) -> None:
        parent = QWidget()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "preview.png")
            self.assertTrue(QImage(2, 2, QImage.Format.Format_RGB32).save(image_path))
            dialog = ImagePreviewDialog("Image", image_path, parent=parent)
            self.assert_is_taskbar_window(dialog)

    def test_entry_details_is_a_top_level_window(self) -> None:
        parent = QWidget()
        dialog = EntryDetailDialog("Details", "metadata", parent=parent)
        self.assert_is_taskbar_window(dialog)


if __name__ == "__main__":
    unittest.main()
