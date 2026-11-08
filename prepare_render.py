"""Restore the deployable UI assets bundled in the repository ZIP.

The tracked Python entry points remain authoritative. Only templates/, static/,
and assets/ are restored from the distributable archive so deploys cannot
silently omit the Flask UI.
"""
from __future__ import annotations

import posixpath
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "RAKOVAR_full_project_MAX_preview.zip"
REQUIRED_TEMPLATES = {"storefront.html", "admin_login.html", "admin.html"}
ALLOWED_DIRS = {"templates", "static", "assets"}


def main() -> int:
    if not ARCHIVE.is_file() or not zipfile.is_zipfile(ARCHIVE):
        print(f"ERROR: required project archive is missing or invalid: {ARCHIVE.name}", file=sys.stderr)
        return 2

    extracted: set[str] = set()
    with zipfile.ZipFile(ARCHIVE) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw = info.filename.replace("\\", "/")
            parts = PurePosixPath(raw).parts
            if not parts or raw.startswith("/") or ".." in parts:
                continue
            target_index = next((i for i, part in enumerate(parts) if part in ALLOWED_DIRS), None)
            if target_index is None or target_index + 1 >= len(parts):
                continue
            folder = parts[target_index]
            relative = PurePosixPath(*parts[target_index + 1:])
            if relative.is_absolute() or ".." in relative.parts:
                continue
            destination = (ROOT / folder / Path(*relative.parts)).resolve()
            if ROOT not in destination.parents:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                output.write(source.read())
            extracted.add(f"{folder}/{relative.as_posix()}")

    found_templates = {Path(item).name for item in extracted if item.startswith("templates/")}
    missing = REQUIRED_TEMPLATES - found_templates
    if missing:
        print("ERROR: archive did not provide required Flask templates: " + ", ".join(sorted(missing)), file=sys.stderr)
        print("Archive members: " + ", ".join(sorted(extracted)[:80]), file=sys.stderr)
        return 3

    print(f"Restored {len(extracted)} UI assets from {ARCHIVE.name}.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
