"""Bundle only hash-verified manifest files, never untracked bookkeeping data."""
import hashlib
import json
from pathlib import Path
import shutil
import sys


def copy_snapshot(source: Path, destination: Path) -> None:
    manifest = source / "SHA256SUMS.json"
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    verified = []
    for relative, expected in entries.items():
        name = Path(relative)
        if name.is_absolute() or ".." in name.parts:
            raise ValueError(f"Unsafe snapshot path: {relative}")
        original = source / name
        if original.is_symlink() or not original.resolve().is_relative_to(source.resolve()):
            raise ValueError(f"Snapshot file must be inside the snapshot: {relative}")
        if hashlib.sha256(original.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Snapshot hash mismatch: {relative}")
        verified.append((original, destination / name))
    destination.mkdir(parents=True, exist_ok=False)
    for original, target in verified:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
    shutil.copyfile(manifest, destination / manifest.name)


if __name__ == "__main__":
    copy_snapshot(Path(sys.argv[1]), Path(sys.argv[2]))
