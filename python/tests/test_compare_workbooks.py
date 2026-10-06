from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
from xml.parsers import expat
import zipfile

from compare_workbooks import (
    assert_workbooks_equal,
    normalize_core_dates,
    workbook_differences,
    workbook_entries,
)

ROOT = Path(__file__).resolve().parents[1]
CORE = b'''<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>Original creator</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">2026-01-02T03:04:05Z</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-02T03:04:05Z</dcterms:modified><cp:revision>1</cp:revision></cp:coreProperties>'''


class WorkbookComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.parts = {
            "[Content_Types].xml": b"<Types/>",
            "docProps/core.xml": CORE,
            "docProps/app.xml": b"<Properties><Application>Excel</Application></Properties>",
            "xl/workbook.xml": b'<workbook><sheets><sheet name="Original"/></sheets></workbook>',
            "xl/worksheets/sheet1.xml": b'<worksheet><cols><col width="12"/></cols><sheetData><c r="A1" s="1"><f>SUM(B2:B3)</f><v>3</v></c></sheetData></worksheet>',
            "xl/styles.xml": b'<styleSheet><numFmts formatCode="#,##0.00"/></styleSheet>',
            "xl/_rels/workbook.xml.rels": b'<Relationships><Relationship Target="worksheets/sheet1.xml"/></Relationships>',
            "_rels/.rels": b"<Relationships/>",
            "xl/media/image1.png": b"binary-image-content",
        }

    def archive(self, name, parts=None, alternate_metadata=False):
        path = self.directory / name
        parts = self.parts if parts is None else parts
        with zipfile.ZipFile(path, "w") as archive:
            items = list(parts.items())
            if alternate_metadata:
                items.reverse()
                archive.comment = b"unimportant archive comment"
            for member, payload in items:
                info = zipfile.ZipInfo(member, (2025 if alternate_metadata else 2020, 1, 2, 3, 4, 6))
                info.compress_type = zipfile.ZIP_DEFLATED if alternate_metadata else zipfile.ZIP_STORED
                info.external_attr = (0o600 if alternate_metadata else 0o644) << 16
                info.comment = b"different metadata" if alternate_metadata else b""
                archive.writestr(info, payload)
        return path

    def test_zip_metadata_compression_and_entry_order_are_ignored(self):
        first = self.archive("first.xlsx")
        second = self.archive("second.xlsx", alternate_metadata=True)
        self.assertNotEqual(first.read_bytes(), second.read_bytes())
        assert_workbooks_equal(first, second)

    def test_only_created_and_modified_values_are_normalized(self):
        updated = dict(self.parts)
        updated["docProps/core.xml"] = CORE.replace(b"2026-01-02T03:04:05Z", b"2030-12-31T23:59:59+00:00")
        assert_workbooks_equal(self.archive("first.xlsx"), self.archive("second.xlsx", updated))
        expected = CORE.replace(b"2026-01-02T03:04:05Z", b"NORMALIZED_TIMESTAMP")
        self.assertEqual(normalize_core_dates(CORE), expected)

    def test_core_creator_revision_attributes_and_xml_formatting_are_not_ignored(self):
        changes = [
            (b"Original creator", b"Different creator"),
            (b"<cp:revision>1", b"<cp:revision>2"),
            (b'dcterms:W3CDTF"', b'dcterms:OtherType"'),
            (b"<dc:creator>", b"\n<dc:creator>"),
        ]
        first = self.archive("first.xlsx")
        for old, new in changes:
            with self.subTest(change=old):
                updated = dict(self.parts, **{"docProps/core.xml": CORE.replace(old, new)})
                self.assertEqual(workbook_differences(first, self.archive("second.xlsx", updated)), ["Different payload: docProps/core.xml"])

    def test_namespace_resolution_and_non_timestamp_dates(self):
        prefixed = CORE.replace(b"dcterms", b"dates")
        self.assertIn(b"NORMALIZED_TIMESTAMP", normalize_core_dates(prefixed))
        unrelated = CORE.replace(b"http://purl.org/dc/terms/", b"urn:unrelated")
        self.assertEqual(normalize_core_dates(unrelated), unrelated)
        for value in (b"not-a-date", b"2026-01-02", b""):
            with self.subTest(value=value):
                changed = CORE.replace(b"2026-01-02T03:04:05Z", value)
                self.assertEqual(normalize_core_dates(changed), changed)

    def test_markup_inside_dates_is_not_dropped(self):
        for markup in (b"<!--retain me-->", b"<?retain me?>"):
            changed = CORE.replace(b"2026-01-02T03:04:05Z", b"2026-01-02T03:04:05Z" + markup)
            self.assertEqual(normalize_core_dates(changed), changed)

    def test_cdata_delimiters_are_preserved_when_normalizing_dates(self):
        changed = CORE.replace(b"2026-01-02T03:04:05Z", b"<![CDATA[2026-01-02T03:04:05Z]]>")
        self.assertEqual(normalize_core_dates(changed), changed.replace(b"2026-01-02T03:04:05Z", b"NORMALIZED_TIMESTAMP"))
        self.assertNotEqual(normalize_core_dates(CORE), normalize_core_dates(changed))
        split = CORE.replace(b"2026-01-02T03:04:05Z", b"<![CDATA[2026-01-02]]><![CDATA[T03:04:05Z]]>")
        self.assertEqual(normalize_core_dates(split), split)

    def test_every_non_core_zip_payload_is_compared_exactly(self):
        first = self.archive("first.xlsx")
        for member in self.parts.keys() - {"docProps/core.xml"}:
            with self.subTest(member=member):
                updated = dict(self.parts)
                updated[member] += b"different"
                differences = workbook_differences(first, self.archive("second.xlsx", updated))
                self.assertEqual(differences, [f"Different payload: {member}"])

    def test_cells_formulas_widths_styles_sheets_and_relationships_are_significant(self):
        first = self.archive("first.xlsx")
        changes = [
            ("xl/worksheets/sheet1.xml", b"<v>3</v>", b"<v>4</v>"),
            ("xl/worksheets/sheet1.xml", b"SUM(B2:B3)", b"SUM(B2:B4)"),
            ("xl/worksheets/sheet1.xml", b'width="12"', b'width="13"'),
            ("xl/worksheets/sheet1.xml", b's="1"', b's="2"'),
            ("xl/styles.xml", b"#,##0.00", b"0.0"),
            ("xl/workbook.xml", b"Original", b"Renamed"),
            ("xl/_rels/workbook.xml.rels", b"sheet1.xml", b"sheet2.xml"),
        ]
        for member, old, new in changes:
            with self.subTest(member=member, change=old):
                updated = dict(self.parts)
                updated[member] = updated[member].replace(old, new)
                with self.assertRaisesRegex(AssertionError, member):
                    assert_workbooks_equal(first, self.archive("second.xlsx", updated))

    def test_added_and_missing_entries_are_reported(self):
        updated = dict(self.parts)
        del updated["xl/media/image1.png"]
        updated["customXml/item1.xml"] = b"<new/>"
        self.assertEqual(workbook_differences(self.archive("first.xlsx"), self.archive("second.xlsx", updated)), ["Only in first: xl/media/image1.png", "Only in second: customXml/item1.xml"])

    def test_invalid_archives_and_duplicate_members_fail(self):
        invalid = self.directory / "invalid.xlsx"
        invalid.write_bytes(b"not a zip")
        with self.assertRaises(zipfile.BadZipFile):
            workbook_entries(invalid)
        with self.assertRaisesRegex(ValueError, "Not an XLSX"):
            workbook_entries(self.archive("missing.xlsx", {"hello.txt": b"hi"}))
        malformed = dict(self.parts, **{"docProps/core.xml": b"<broken"})
        with self.assertRaises(expat.ExpatError):
            workbook_entries(self.archive("broken.xlsx", malformed))
        duplicate = self.archive("duplicate.xlsx")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(duplicate, "a") as archive:
                archive.writestr("xl/workbook.xml", b"duplicate")
        with self.assertRaisesRegex(ValueError, "Duplicate ZIP entry"):
            workbook_entries(duplicate)

    def test_cli_equivalent_difference_and_error_exit_codes(self):
        first = self.archive("first.xlsx")
        equivalent = self.archive("equivalent.xlsx", alternate_metadata=True)
        changed = self.archive("changed.xlsx", dict(self.parts, **{"xl/styles.xml": b"changed"}))
        for second, code, message in [(equivalent, 0, "Equivalent"), (changed, 1, "xl/styles.xml"), (self.directory / "missing.xlsx", 2, "Comparison error")]:
            with self.subTest(second=second):
                result = subprocess.run([sys.executable, str(ROOT / "compare_workbooks.py"), str(first), str(second)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn(message, result.stdout)


if __name__ == "__main__":
    unittest.main()
