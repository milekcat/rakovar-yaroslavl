"""Reviewed, per-product catalog snapshot; company approval is outstanding.

Source offers and conflicts live in docs/research, outside customer copy.
No network request or archive extraction occurs during startup or builds.
"""
import json
from pathlib import Path

EDA7_URL = "https://eda7.ru/yaroslavl/rest/rakovar-fnxcs/"
CHIBBIS_URL = "https://chibbis.ru/yar/restaurant/rakovar/menu"
EDA_DOSTAVKA_URL = "https://eda-dostavka.com/yaroslavl/restorany/rakovar-fnxcs/"
SOURCE_URL = EDA7_URL
CATALOG_VERSION = "store-2026-11-11-v10"
NON_BRAND_PRODUCT_TERMS = ("пицц", "pizza", "пепперони", "pepperoni", "военные раки")
# Opaque upstream banner filenames evade title-only checks.
REJECTED_MEDIA_IDS = ("df9c6ef11fd698f6963dbb540a41dc1f",)
RETIRED_UNVERIFIED_IDS = (
    "crayfish-standart-trad", "crayfish-standart-pennoy", "crayfish-standart-village",
    "crayfish-standart-sourcream", "crayfish-standart-honey", "crayfish-mexican",
    "set-atlanticheskiy", "gift-set-1", "gift-set-2",
)


def is_non_brand_product(product):
    fields = ("title", "category", "description", "image", "badge", "image_url")
    haystack = " ".join(str(product.get(field, "") or "") for field in fields).casefold()
    return any(term in haystack for term in NON_BRAND_PRODUCT_TERMS + REJECTED_MEDIA_IDS)


CATALOG_PRODUCTS = json.loads((Path(__file__).parent / "data/catalog.json").read_text(encoding="utf-8"))
if any(is_non_brand_product(product) for product in CATALOG_PRODUCTS):
    raise ValueError("The curated catalog contains unrelated content")
