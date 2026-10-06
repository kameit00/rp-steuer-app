"""Verify a packaged app without requiring any third-party Python dependencies.

Usage: python verify_app.py APP --arch arm64 --version 1.1.0 --build 2
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
from xml.parsers.expat import ExpatError


APP_NAME = "RP Steuer App"
MACHO_MAGICS = frozenset((
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",  # 32-bit, either byte order
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",  # 64-bit, either byte order
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",  # fat, either byte order
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",  # fat64, either byte order
))
DEPENDENCIES = {
    "numpy": "2.3.3",
    "pandas": "2.3.2",
    "openpyxl": "3.1.5",
    "xlsxwriter": "3.2.9",
}


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, **kwargs)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"Could not execute {command[0]}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"{command[0]} failed (exit {result.returncode}): {detail}")
    return result


def verify_app(app_path: str | Path, expected_arch: str, version: str, build: str | int) -> str:
    """Raise ValueError on an invalid bundle; otherwise return a concise summary."""
    if expected_arch not in ("arm64", "x86_64"):
        raise ValueError(f"Unsupported architecture: {expected_arch}")
    app = Path(app_path).resolve()
    try:
        with (app / "Contents/Info.plist").open("rb") as stream:
            metadata = plistlib.load(stream)
    except (OSError, ValueError, plistlib.InvalidFileException, ExpatError) as error:
        raise ValueError(f"Cannot read {app}/Contents/Info.plist: {error}") from error
    expected_metadata = {
        "CFBundleIdentifier": "com.relax-pillow.rpsteuerapp",
        "CFBundleDisplayName": APP_NAME,
        "CFBundleName": APP_NAME,
        "CFBundleExecutable": "RPSteuerApp",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": str(build),
        "LSMinimumSystemVersion": "14.0",
    }
    if not isinstance(metadata, dict):
        raise ValueError("Info.plist must contain a dictionary")
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            raise ValueError(f"Info.plist {key}: expected {expected!r}, got {metadata.get(key)!r}")

    main = app / "Contents/MacOS/RPSteuerApp"
    engine = app / "Contents/Resources/engine/rp-steuer-app-engine/rp-steuer-app-engine"
    for executable in (main, engine):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"Missing or non-executable binary: {executable}")

    native_files = set()
    for path in sorted(app.rglob("*")):
        if not path.is_file():
            continue
        try:
            with path.open("rb") as stream:
                magic = stream.read(4)
        except OSError as error:
            raise ValueError(f"Cannot inspect {path}: {error}") from error
        if magic not in MACHO_MAGICS:
            continue
        # lipo is authoritative: recognized but malformed files must fail, not be skipped.
        resolved = path.resolve()
        if resolved in native_files:
            continue
        architectures = _run(["/usr/bin/lipo", "-archs", str(path)]).stdout.split()
        if expected_arch not in architectures:
            raise ValueError(f"{path}: expected {expected_arch}, found {' '.join(architectures) or 'no architectures'}")
        native_files.add(resolved)
    for executable in (main, engine):
        if executable.resolve() not in native_files:
            raise ValueError(f"Executable is not a Mach-O binary: {executable}")

    # Do not inherit Python, dynamic-loader, or other developer environment overrides.
    result = _run([str(engine), "--diagnostics"], env={"HOME": str(Path.home()), "PATH": "/usr/bin:/bin"})
    try:
        diagnostics = json.loads(result.stdout)
    except (ValueError, TypeError) as error:
        raise ValueError("Engine did not return valid diagnostics JSON") from error
    if not isinstance(diagnostics, dict):
        raise ValueError("Engine diagnostics must be a JSON object")
    for key, expected in {
        "type": "diagnostics", "app": APP_NAME, "version": version, "architecture": expected_arch,
    }.items():
        if diagnostics.get(key) != expected:
            raise ValueError(f"Engine diagnostics {key}: expected {expected!r}, got {diagnostics.get(key)!r}")
    dependencies = diagnostics.get("dependencies")
    if not isinstance(dependencies, dict):
        raise ValueError("Engine diagnostics are missing dependencies")
    for name, expected in DEPENDENCIES.items():
        if dependencies.get(name) != expected:
            raise ValueError(f"Engine dependency {name}: expected {expected}, got {dependencies.get(name)!r}")
    return f"Verified {APP_NAME} {version} (build {build}), {expected_arch}: {len(native_files)} Mach-O files; engine diagnostics OK."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--arch", required=True, choices=("arm64", "x86_64"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True)
    args = parser.parse_args()
    try:
        print(verify_app(args.app, args.arch, args.version, args.build))
    except ValueError as error:
        parser.exit(1, f"App verification failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
