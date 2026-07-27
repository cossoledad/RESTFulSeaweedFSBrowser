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

    def test_f3d_runtime_files_are_packaged_recursively(self) -> None:
        build_script = Path("build.ps1").read_text(encoding="utf-8")
        self.assertIn(
            "Get-ChildItem -Path $ResolvedF3dBinDir -File -Recurse",
            build_script,
        )
        self.assertIn("=f3d/bin/$relativeBinPath", build_script)


if __name__ == "__main__":
    unittest.main()
