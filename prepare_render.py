"""Restore the deployable UI assets bundled in the repository ZIP."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "RAKOVAR_full_project_MAX_preview.zip"
REQUIRED = {"storefront.html", "admin_login.html", "admin.html"}
ALLOWED_DIRS = {"templates", "static", "assets"}


def main() -> int:
    if not ARCHIVE.is_file() or not zipfile.is_zipfile(ARCHIVE):
        print("ERROR: RAKOVAR_full_project_MAX_preview.zip is missing or invalid", file=sys.stderr)
        return 2

    extracted: list[str] = []
    template_candidates: dict[str, list[tuple[zipfile.ZipInfo, int]]] = {}
    with zipfile.ZipFile(ARCHIVE) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw = info.filename.replace("\\", "/")
            parts = PurePosixPath(raw).parts
            if not parts or raw.startswith("/") or ".." in parts:
                continue
            indexes = [i for i, part in enumerate(parts) if part in ALLOWED_DIRS]
            if not indexes:
                continue
            index = indexes[0]
            folder = parts[index]
            relative = PurePosixPath(*parts[index + 1:])
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                continue
            if folder == "templates":
                template_candidates.setdefault(relative.name, []).append((info, index))
            destination = (ROOT / folder / Path(*relative.parts)).resolve()
            if ROOT not in destination.parents:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                output.write(source.read())
            extracted.append(f"{folder}/{relative.as_posix()}")

        # Normalize the three Flask entry templates to the exact root expected
        # by render_template(), even if the ZIP has an extra directory level.
        for filename in REQUIRED:
            candidates = template_candidates.get(filename, [])
            if candidates:
                info, _ = candidates[0]
                destination = ROOT / "templates" / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as output:
                    output.write(source.read())

    missing = [name for name in REQUIRED if not (ROOT / "templates" / name).is_file()]
    print("Restored UI files: " + ", ".join(sorted(extracted)), flush=True)
    if missing:
        print("ERROR: required Flask templates absent from archive: " + ", ".join(sorted(missing)), file=sys.stderr)
        return 3
    print("Verified required Flask templates: " + ", ".join(sorted(REQUIRED)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
