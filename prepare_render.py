"""Validate checked-in preview sources without modifying or extracting them.

Templates, scripts and styles are ordinary repository files. The historical ZIP
is retained for reference only and is never read during a build.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = (
    "templates/storefront.html",
    "templates/admin_login.html",
    "templates/admin.html",
    "static/app.css",
    "static/brand-refresh.css",
    "static/storefront.js",
    "static/admin.js",
)
STATIC_REFERENCE = re.compile(
    r"url_for\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]"
)


def validate_sources(root: Path = ROOT) -> list[str]:
    """Return errors for absent sources or invalid literal template asset paths."""
    root = root.resolve()
    errors = []
    for relative in REQUIRED:
        path = root / relative
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing or empty source: {relative}")
        elif root not in path.resolve().parents:
            errors.append(f"source points outside project: {relative}")

    for template in sorted((root / "templates").glob("*.html")):
        if not template.is_file() or root not in template.resolve().parents:
            continue
        for filename in STATIC_REFERENCE.findall(template.read_text(encoding="utf-8")):
            asset = root / "static" / filename
            if root / "static" not in asset.resolve().parents or not asset.is_file():
                errors.append(f"invalid or missing static asset in {template.name}: {filename}")
    return errors


def main() -> int:
    errors = validate_sources()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print("Verified checked-in Flask templates and static assets; no files changed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
