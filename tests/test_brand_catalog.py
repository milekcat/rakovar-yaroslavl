"""Regressions for the stale banner, untraceable imports and guarded seed upgrade."""
import hashlib
import json
from pathlib import Path

from catalog_seed import CATALOG_PRODUCTS, CATALOG_VERSION, is_non_brand_product
from test_app import app_module, client, admin_login

ROOT = Path(__file__).resolve().parents[1]


def test_menu_coverage_and_product_specific_media():
    products = {p['id']: p for p in CATALOG_PRODUCTS}
    audit = json.loads((ROOT/'docs/research/media-audit-2026-11-10.json').read_text())
    assets = {a['url']: a for a in audit['assets']}
    all_offers = []
    for source in ('eda7', 'chibbis'):
        offers = json.loads((ROOT/f'docs/research/{source}-menu-2026-11-10.json').read_text())['offers']
        all_offers.extend(offers)
        for offer in offers:
            product = products[offer['catalog_id']]
            assert any(e['source'] == source for e in product['evidence'])
            assert offer['image_url'] in assets
    for product in products.values():
        path = ROOT/'static/images'/product['image']
        assert path.is_file(), product['id']
        assert not product['image_url']  # No upstream fallback can load a restaurant banner.
        assert product['weight'].strip() != '1 г'
        if path.suffix != '.svg':
            asset = next(a for a in assets.values() if ROOT/a['file'] == path)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == asset['sha256']
            assert asset['url'] in {offer['image_url'] for offer in all_offers if offer['catalog_id'] == product['id']}
    bacon = products['langoustine-bacon']
    assert bacon['price_on_request'] == 1 and bacon['price'] == 0


def test_opaque_pizza_banner_is_rejected_in_api_and_legacy_rows(client, app_module):
    banner = 'https://scdn.chibbis.ru/live/banners/df9c6ef11fd698f6963dbb540a41dc1f.png'
    assert is_non_brand_product({'title': 'Морское ассорти', 'image_url': banner})
    csrf = admin_login(client)
    response = client.patch('/api/admin/products/set-4-morya',
                            headers={'X-CSRF-Token': csrf}, json={'image_url': banner})
    assert response.status_code == 400
    with app_module.connect_db() as connection:
        connection.execute("UPDATE products SET image_url=? WHERE id='set-4-morya'", (banner,))
    assert 'set-4-morya' not in {p['id'] for p in client.get('/api/bootstrap').json['products']}
    assert client.post('/api/checkout/quote', json={'items':[{'id':'set-4-morya','quantity':1}],'delivery_mode':'pickup'}).status_code == 409


def test_seed_upgrade_archives_unapproved_rows_and_preserves_operator_data(app_module):
    with app_module.connect_db() as c:
        c.execute("UPDATE site_settings SET setting_value='previous-snapshot' WHERE setting_key='catalog_seed_version'")
        c.execute("UPDATE products SET price=777,description='Утверждено компанией',price_verified=1,stock_confirmed=1,stock=7 WHERE id='set-classic'")
        c.execute("UPDATE products SET description='Позиция из публичного меню. Состав подтвердить.',image_url='https://example.invalid/old.jpg' WHERE id='shrimp-king-boiled'")
        for pid, approved in [('crayfish-standart-trad',0),('gift-set-1',1)]:
            c.execute("INSERT INTO products(id,title,category,price,unit,stock,description,image,badge,created_at,price_verified,stock_confirmed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (pid,'Исторический товар','Раки',777,'за кг',7,'Сохранить историю','opt_crayfish.svg','Раки','now',approved,approved))
        c.execute("UPDATE site_settings SET setting_value='Текст компании' WHERE setting_key='footer_notice'")
    app_module.init_db()
    app_module.init_db()  # Startup must be repeatable.
    with app_module.connect_db() as c:
        approved = dict(c.execute("SELECT * FROM products WHERE id='set-classic'").fetchone())
        assert (approved['price'],approved['stock'],approved['description']) == (777,7,'Утверждено компанией')
        assert c.execute("SELECT active FROM products WHERE id='crayfish-standart-trad'").fetchone()[0] == 0
        assert c.execute("SELECT active FROM products WHERE id='gift-set-1'").fetchone()[0] == 1
        fresh = dict(c.execute("SELECT * FROM products WHERE id='shrimp-king-boiled'").fetchone())
        assert not fresh['image_url'] and fresh['image'].startswith('menu/')
        assert c.execute("SELECT setting_value FROM site_settings WHERE setting_key='catalog_seed_version'").fetchone()[0] == CATALOG_VERSION
        assert c.execute("SELECT setting_value FROM site_settings WHERE setting_key='footer_notice'").fetchone()[0] == 'Текст компании'


def test_delivery_quote_marks_estimate_without_adopting_aggregator_minimum(client, app_module):
    response = client.post('/api/checkout/quote',json={'items':[{'id':'sauce-cheese','quantity':1}],'delivery_mode':'delivery'})
    assert response.status_code == 200
    assert response.json['delivery_status'] == 'estimate'
    assert response.json['delivery_finalized'] is False
    assert response.json['delivery_rub'] == app_module.PREVIEW_DELIVERY_RUB
