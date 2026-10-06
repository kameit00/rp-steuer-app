"""Fail builds with inconsistent release metadata. VERSION is authoritative."""
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def check(root: Path = ROOT) -> tuple[str, str]:
    version = (root / "VERSION").read_text().strip()
    build = (root / "BUILD_NUMBER").read_text().strip()
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError("VERSION must contain a stable SemVer release (e.g. 1.0.0)")
    if not re.fullmatch(r"[1-9]\d*", build):
        raise ValueError("BUILD_NUMBER must be a positive integer")
    project = tomllib.loads((root / "python/pyproject.toml").read_text())["project"]
    if project["name"] != "rp-steuer-app-engine" or project["version"] != version:
        raise ValueError("Python project name/version must match RP Steuer App and VERSION")
    lock = tomllib.loads((root / "python/uv.lock").read_text())
    if not any(p["name"] == project["name"] and p["version"] == version for p in lock["package"]):
        raise ValueError("Refresh python/uv.lock after changing the project version")
    if not re.search(rf"^## \[{re.escape(version)}\] — \d{{4}}-\d{{2}}-\d{{2}}$", (root / "CHANGELOG.md").read_text(), re.M):
        raise ValueError("CHANGELOG.md needs a dated entry for VERSION")
    return version, build


if __name__ == "__main__":
    version, build = check()
    print(f"RP Steuer App {version} (build {build})")
