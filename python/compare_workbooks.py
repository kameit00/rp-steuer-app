"""Compare every XLSX ZIP payload, ignoring ZIP metadata and core date values only.

This deliberately does not load/resave or canonicalize worksheets: formulas, cached
values, formatting, column widths, relationships and all other bytes must match.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from xml.parsers import expat
import zipfile

CORE_PART = "docProps/core.xml"
DCTERMS = "http://purl.org/dc/terms/"


def normalize_core_dates(data: bytes) -> bytes:
    """Replace only valid dcterms:created/modified text; preserve other XML bytes.

    Expat resolves namespaces and supplies byte offsets, so namespace prefixes,
    attributes, creator metadata and even XML formatting remain significant.
    """
    parser = expat.ParserCreate(namespace_separator="|")
    targets = {f"{DCTERMS}|created", f"{DCTERMS}|modified"}
    replacements: list[tuple[int, int]] = []
    active = None
    depth = 0

    def start(name, attributes):
        nonlocal active, depth
        depth += 1
        if active is not None:
            active["nested"] = True
        if name in targets and active is None:
            # Locate the end of the opening tag without mistaking '>' in a
            # quoted attribute for the tag terminator.
            index = parser.CurrentByteIndex
            quote = None
            while index < len(data):
                char = data[index]
                if quote is not None:
                    if char == quote:
                        quote = None
                elif char in (34, 39):
                    quote = char
                elif char == 62:
                    break
                index += 1
            active = {"start": index + 1, "depth": depth, "text": [], "nested": False}

    def text(value):
        if active is not None:
            active["text"].append(value)

    def end(name):
        nonlocal active, depth
        if active is not None and active["depth"] == depth:
            value = "".join(active["text"])
            try:
                # Dates without a time are not timestamps and remain significant.
                if "T" not in value:
                    raise ValueError("Not a timestamp")
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
            else:
                if not active["nested"]:
                    first, last = active["start"], parser.CurrentByteIndex
                    raw_text = data[first:last]
                    # CDATA delimiters are XML structure, not timestamp text.
                    simple_text = b"<![CDATA[" not in raw_text
                    single_cdata = (raw_text.startswith(b"<![CDATA[") and raw_text.endswith(b"]]>")
                                    and raw_text.count(b"<![CDATA[") == 1)
                    if single_cdata:
                        first += len(b"<![CDATA[")
                        last -= len(b"]]>")
                    # Preserve unusual mixed text/CDATA structure exactly.
                    if simple_text or single_cdata:
                        replacements.append((first, last))
            active = None
        depth -= 1

    def markup(*arguments):
        if active is not None:
            active["nested"] = True

    parser.StartElementHandler = start
    parser.CharacterDataHandler = text
    parser.EndElementHandler = end
    parser.CommentHandler = markup
    parser.ProcessingInstructionHandler = markup
    parser.Parse(data, True)
    for start_index, end_index in reversed(replacements):
        data = data[:start_index] + b"NORMALIZED_TIMESTAMP" + data[end_index:]
    return data


def workbook_entries(path: str | Path) -> dict[str, bytes]:
    """Read all entries (including non-XML parts), rejecting ambiguous duplicates."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate ZIP entry in {path}")
        entries = {name: archive.read(name) for name in names}
    if "xl/workbook.xml" not in entries:
        raise ValueError(f"Not an XLSX workbook: {path}")
    if CORE_PART in entries:
        entries[CORE_PART] = normalize_core_dates(entries[CORE_PART])
    return entries


def workbook_differences(left: str | Path, right: str | Path) -> list[str]:
    """Return entry-level differences; invalid archives raise an exception."""
    first, second = workbook_entries(left), workbook_entries(right)
    differences = [f"Only in first: {name}" for name in sorted(first.keys() - second.keys())]
    differences += [f"Only in second: {name}" for name in sorted(second.keys() - first.keys())]
    differences += [
        f"Different payload: {name}"
        for name in sorted(first.keys() & second.keys())
        if first[name] != second[name]
    ]
    return differences


def assert_workbooks_equal(left: str | Path, right: str | Path) -> None:
    differences = workbook_differences(left, right)
    if differences:
        raise AssertionError(f"Workbooks differ: {left} vs {right}\n" + "\n".join(differences))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args(argv)
    try:
        differences = workbook_differences(args.first, args.second)
    except Exception as error:
        print(f"Comparison error: {error}")
        return 2
    if differences:
        print("\n".join(differences))
        return 1
    print("Equivalent (all ZIP payloads match except core created/modified timestamps).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
