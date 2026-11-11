from catalog_seed import CATALOG_PRODUCTS, is_non_brand_product


def test_curated_catalog_has_no_unrelated_legacy_items():
    assert all(not is_non_brand_product(product) for product in CATALOG_PRODUCTS)


def test_pizzeria_and_mislabelled_items_are_blocked():
    assert is_non_brand_product({"title": "Пицца Пепперони", "category": "Пицца"})
    assert is_non_brand_product({"title": "Pepperoni", "category": "Пицца"})
    assert is_non_brand_product({"title": "Военные раки", "category": "Раки"})


def test_rakovar_products_remain_allowed():
    assert not is_non_brand_product({"title": "Раки варёные", "category": "Раки"})
    assert not is_non_brand_product({"title": "Сет «Атлантический»", "category": "Сеты"})
    assert not is_non_brand_product({"title": "Съедобный букет из морепродуктов", "category": "Подарки"})
