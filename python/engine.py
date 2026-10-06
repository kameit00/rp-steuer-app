"""Transport/safety adapter. Excel generation lives in untouched production files."""
from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import io
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

PRODUCTION = Path(__file__).resolve().parent / "production"
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
if not VERSION_FILE.is_file():
    VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
sys.path.insert(0, str(PRODUCTION))

from rp_steuer.sevdesk_csv_to_excel import convert_csv_to_excel
from rp_steuer.sevdesk_paypal import process_csv_files


class JobError(Exception):
    pass


def emit(event: dict) -> None:
    # Never send production print output directly through the JSON transport.
    sys.__stdout__.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.__stdout__.flush()


class LogCapture(io.TextIOBase):
    def __init__(self, report: Callable[[dict], None]):
        self.report = report
        self.pending = ""
        self.processing_errors: list[str] = []

    def write(self, text: str) -> int:
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self.line(line)
        return len(text)

    def line(self, line: str) -> None:
        if line:
            self.report({"type": "log", "message": line})
            if line.startswith("Error") or line.startswith("Failed"):
                self.processing_errors.append(line)

    def flush(self) -> None:
        if self.pending:
            self.line(self.pending)
            self.pending = ""


def load_rules(path: Path) -> None:
    """Validate transport input, without changing production rule matching."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        rules = data
    elif isinstance(data, dict) and isinstance(data.get("rules"), list):
        rules = data["rules"]
        categories = data.get("always_show_in_summary", [])
        if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
            raise JobError("always_show_in_summary muss eine Liste von Texten sein.")
    else:
        raise JobError("rules.json muss eine Regelliste oder ein Objekt mit 'rules' enthalten.")
    for rule in rules:
        if not isinstance(rule, dict) or not all(
            isinstance(rule.get(key), str)
            for key in ("column", "substring", "info_column_value")
        ):
            raise JobError("Jede Regel benötigt column, substring und info_column_value als Text.")


def run_job(request: dict, report: Callable[[dict], None] = emit) -> list[str]:
    if not isinstance(request, dict):
        raise JobError("Ungültiger Auftrag.")
    mode = request.get("mode")
    if mode not in ("paypal", "sevdesk"):
        raise JobError("Bitte PayPal oder sevDesk auswählen.")
    raw_inputs = request.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs or not all(isinstance(p, str) for p in raw_inputs):
        raise JobError("Bitte mindestens eine CSV-Datei auswählen.")
    inputs = [Path(p).expanduser().resolve() for p in raw_inputs]
    if len(set(inputs)) != len(inputs):
        raise JobError("Dieselbe CSV-Datei wurde mehrfach ausgewählt.")
    for source in inputs:
        if not source.is_file() or source.suffix.lower() != ".csv" or source.name.startswith("._"):
            raise JobError(f"Keine lesbare CSV-Datei: {source}")
    raw_output = request.get("output_directory")
    if not isinstance(raw_output, str) or not raw_output:
        raise JobError("Bitte einen Ausgabeordner auswählen.")
    output = Path(raw_output).expanduser().resolve()
    if not output.is_dir():
        raise JobError(f"Ausgabeordner existiert nicht: {output}")
    rules = None
    if mode == "paypal":
        raw_rules = request.get("rules_file")
        if raw_rules is not None and not isinstance(raw_rules, str):
            raise JobError("Ungültiger Regeldateipfad.")
        rules = Path(raw_rules).expanduser().resolve() if raw_rules else PRODUCTION / "rules.json"
        load_rules(rules)

    # A separate staging directory per input prevents production PayPal's silent
    # overwrites and invoice skips. Fail the WHOLE job on duplicate output names.
    # Never delete originals or overwrite an existing destination file.
    with tempfile.TemporaryDirectory(prefix="rp-steuer-app-") as temporary:
        staged: dict[str, Path] = {}
        for index, source in enumerate(inputs):
            report({"type": "log", "message": f"[{index + 1}/{len(inputs)}] {source.name}"})
            work = Path(temporary) / str(index)
            work.mkdir()
            # The production glob only sees lower-case .csv extensions.
            staged_name = source.stem + ".csv"
            if mode == "paypal" and staged_name.startswith("."):
                # glob('*.csv') ignores dotfiles. PayPal output names depend only
                # on dates, so a visible staging prefix cannot change Excel data.
                staged_name = "input-" + staged_name
            csv_copy = work / staged_name
            shutil.copyfile(source, csv_copy)
            capture = LogCapture(report)
            result = None
            with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
                try:
                    if mode == "paypal":
                        shutil.copyfile(rules, work / "rules.json")
                        process_csv_files(delete_csv=False, directory=str(work))
                    else:
                        result = convert_csv_to_excel(str(csv_copy))
                finally:
                    capture.flush()
            if capture.processing_errors:
                raise JobError("\n".join(capture.processing_errors))
            generated = sorted(work.glob("*.xlsx"))
            if not generated or (mode == "sevdesk" and result is None):
                raise JobError(f"Keine Excel-Datei erzeugt: {source.name}. Bitte das Protokoll prüfen.")
            for workbook in generated:
                with zipfile.ZipFile(workbook) as archive:
                    if archive.testzip() is not None or "xl/workbook.xml" not in archive.namelist():
                        raise JobError(f"Ungültige Excel-Datei: {workbook.name}")
                # macOS destination volumes are commonly case insensitive.
                key = workbook.name.casefold()
                if key in staged:
                    raise JobError(
                        f"Mehrere CSVs erzeugen {workbook.name}. Bitte einzeln in verschiedene Ordner verarbeiten. "
                        "Es wurde nichts gespeichert."
                    )
                staged[key] = workbook

        existing = {p.name.casefold() for p in output.iterdir()}
        for key, workbook in staged.items():
            if key in existing:
                raise JobError(f"{workbook.name} existiert bereits. Bitte einen leeren Ausgabeordner wählen.")

        published: list[Path] = []
        try:
            for workbook in staged.values():
                destination = output / workbook.name
                # Exclusive creation protects against concurrent jobs/races too.
                with destination.open("xb") as target:
                    published.append(destination)
                    with workbook.open("rb") as source:
                        shutil.copyfileobj(source, target)
        except BaseException:
            for destination in published:
                destination.unlink(missing_ok=True)
            raise
        files = [str(p) for p in published]
        report({"type": "log", "message": f"{len(files)} Excel-Datei(en) gespeichert. Original-CSVs bleiben unverändert."})
        return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path)
    parser.add_argument("--diagnostics", action="store_true")
    args = parser.parse_args()
    if args.diagnostics:
        emit({"type": "diagnostics", "app": "RP Steuer App", "version": APP_VERSION,
              "python": sys.version, "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "openpyxl", "xlsxwriter")
        }})
        return 0
    if args.request is None:
        parser.error("--request wird benötigt")
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        files = run_job(request)
        emit({"type": "result", "success": True, "files": files})
        return 0
    except Exception as error:
        emit({"type": "result", "success": False, "files": [], "error": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
