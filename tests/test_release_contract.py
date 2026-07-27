import re
import unittest
from pathlib import Path

from seaweed_browser.core import APP_VERSION


class ReleaseContractTests(unittest.TestCase):
    def test_version_is_consistent_across_release_inputs(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        self.assertIn(f"当前版本：`{APP_VERSION}`", readme)
        self.assertTrue(Path(f"release-notes/v{APP_VERSION}.md").is_file())

    def test_build_reads_version_from_core_module(self) -> None:
        build_script = Path("build.ps1").read_text(encoding="utf-8")
        self.assertIn('$VersionFile = "seaweed_browser/core.py"', build_script)

    def test_release_job_is_tag_only(self) -> None:
        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        release_job = workflow[workflow.index("\n  release:") :]
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", release_job)
        self.assertNotRegex(
            release_job,
            re.compile(r"github\.ref == 'refs/heads/(main|master)'"),
        )

    def test_model_preview_uses_packaged_qt_quick_resource(self) -> None:
        build_script = Path("build.ps1").read_text(encoding="utf-8")
        self.assertIn("--include-data-dir=resource=resource", build_script)
        self.assertIn("--include-qt-plugins=all", build_script)
        self.assertNotIn("--include-package=f3d", build_script)
        self.assertTrue(Path("resource/model_preview.qml").is_file())

    def test_model_preview_is_a_single_qt_quick_window(self) -> None:
        main_source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("class ModelPreviewWindow(QMainWindow):", main_source)
        self.assertIn("self.setWindowIcon(get_app_window_icon())", main_source)
        self.assertIn("viewer = QQuickWidget(self)", main_source)
        self.assertIn("configure_logging(", main_source)
        self.assertIn("root.modelLoadFailed.connect", main_source)
        self.assertNotIn("import f3d", main_source)
        self.assertNotIn("SetParent", main_source)


if __name__ == "__main__":
    unittest.main()
