"""Dependency-light source checks; database/API behavior is covered by pytest."""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalog_seed import CATALOG_PRODUCTS, is_non_brand_product
from prepare_render import validate_sources

errors = validate_sources(ROOT)
if errors:
    raise SystemExit("\n".join(errors))

python_files = sorted({
    path
    for folder in (ROOT, ROOT / "tests", ROOT / "scripts")
    for path in folder.glob("*.py")
})
for path in python_files:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path.relative_to(ROOT)))

javascript_files = sorted((ROOT / "static").rglob("*.js"))
for path in javascript_files:
    subprocess.run(["node", "--check", str(path)], check=True)

ids = [product["id"] for product in CATALOG_PRODUCTS]
assert len(ids) >= 60
assert len(ids) == len(set(ids)), "Catalog IDs must be unique"
assert not any(is_non_brand_product(product) for product in CATALOG_PRODUCTS)
assert all(product["price_verified"] == 0 for product in CATALOG_PRODUCTS)
assert all(product["stock_confirmed"] == 0 for product in CATALOG_PRODUCTS)
for product in CATALOG_PRODUCTS:
    # Existing aggregator images are preview references, not proof of usage rights.
    # Accept only HTTPS hotlinks without embedded credentials.
    if product.get("image_url"):
        image = urlsplit(product["image_url"])
        assert image.scheme == "https" and image.hostname
        assert image.username is None and image.password is None

print(
    f"PASS: {len(python_files)} Python and {len(javascript_files)} JavaScript sources, "
    f"static references, {len(CATALOG_PRODUCTS)} unverified catalog items. "
    "Run pytest for database and API checks."
)
