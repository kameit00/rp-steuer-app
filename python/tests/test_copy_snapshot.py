import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from copy_snapshot import copy_snapshot


class SnapshotPackagingTests(unittest.TestCase):
    def test_only_verified_manifest_files_are_copied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "rules.json").write_text('{"rules":[]}')
            (source / "customer.csv").write_text("confidential")
            (source / "financial-report.xlsx").write_bytes(b"confidential")
            manifest = {"rules.json": hashlib.sha256((source / "rules.json").read_bytes()).hexdigest()}
            (source / "SHA256SUMS.json").write_text(json.dumps(manifest))
            destination = root / "bundle"
            copy_snapshot(source, destination)
            self.assertEqual({p.name for p in destination.iterdir()}, {"rules.json", "SHA256SUMS.json"})
            self.assertEqual((destination / "rules.json").read_bytes(), (source / "rules.json").read_bytes())

    def test_tampered_or_unsafe_entries_fail_before_copying(self):
        for name, value in [("rules.json", "wrong"), ("../secret.csv", "wrong"), ("/absolute", "wrong")]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / "source"
                source.mkdir()
                (source / "rules.json").write_text("{}")
                (source / "SHA256SUMS.json").write_text(json.dumps({name: value}))
                destination = Path(temporary) / "bundle"
                with self.assertRaises(ValueError):
                    copy_snapshot(source, destination)
                self.assertFalse(destination.exists())
