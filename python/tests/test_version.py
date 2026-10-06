from pathlib import Path
import tempfile
import unittest

from check_version import ROOT, check


class VersionTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "python").mkdir()
        (root / "VERSION").write_text("1.0.0\n")
        (root / "BUILD_NUMBER").write_text("1\n")
        (root / "python/pyproject.toml").write_text('[project]\nname="rp-steuer-app-engine"\nversion="1.0.0"\n')
        (root / "python/uv.lock").write_text('[[package]]\nname="rp-steuer-app-engine"\nversion="1.0.0"\n')
        (root / "CHANGELOG.md").write_text("## [1.0.0] — 2026-10-06\n")
        return root

    def test_project_release_metadata_is_consistent(self):
        version, build = check(ROOT)
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertTrue(int(build) > 0)

    def test_inconsistent_versions_lock_changelog_and_invalid_numbers_fail(self):
        for path, value in [
            ("VERSION", "01.0.0"), ("VERSION", "bad"), ("BUILD_NUMBER", "0"),
            ("BUILD_NUMBER", "1; touch something"),
            ("python/pyproject.toml", '[project]\nname="rp-steuer-app-engine"\nversion="2.0.0"\n'),
            ("python/uv.lock", '[[package]]\nname="rp-steuer-app-engine"\nversion="2.0.0"\n'),
            ("CHANGELOG.md", "## [2.0.0] — 2026-10-06\n"),
        ]:
            with self.subTest(path=path, value=value):
                root = self.fixture()
                (root / path).write_text(value)
                with self.assertRaises(ValueError):
                    check(root)
