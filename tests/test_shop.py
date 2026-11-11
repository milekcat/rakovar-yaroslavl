"""Customer/shop contracts: no forged prices, contacts or stock shortcuts."""
import json
import uuid
import pytest
from test_app import app_module, client, admin_login

@pytest.fixture()
def shop(client,app_module,monkeypatch):
    monkeypatch.setenv('INTEGRATION_ENCRYPTION_KEY','synthetic-shop-encryption-master-key-32')
    profile=client.get('/api/store/profile').json
    return client,app_module,{'X-CSRF-Token':profile['csrf_token']},profile['guest_id']

def payload(**changes):
    return {'items':[{'id':'crayfish-medium-kg','quantity':1}], 'name':'Синтетический покупатель',
            'phone':'+79990001111','delivery_mode':'pickup','consent':True,'payment_method':'on_receipt',**changes}

def order(client,headers,**changes):
    return client.post('/api/store/orders',headers={**headers,'Idempotency-Key':uuid.uuid4().hex},json=payload(**changes))

def test_catalog_has_five_buyable_live_sizes_and_no_unpriced_vk_links(shop):
    c,a,h,g=shop
    products=c.get('/api/store/catalog').json['products']
    assert len([p for p in products if p.get('live_size')])==5
    assert all(p['price']>0 and not p['price_on_request'] for p in products)
    assert all(not p['image'].endswith('.svg') for p in products)
    html=c.get('/').text
    assert '/admin' not in html and 'Для команды' not in html
    assert '/account' in html

def test_server_quote_fractional_weight_and_delivery_rules(shop):
    c,a,h,g=shop
    q=c.post('/api/store/quote',headers=h,json=payload(items=[{'id':'live-crayfish-standart-kg','quantity':1.5,'price':1}])).json
    assert q['subtotal_rub']==5685 and q['total_rub']==5685
    assert c.post('/api/store/quote',headers=h,json=payload(items=[{'id':'live-crayfish-standart-kg','quantity':.3}])).status_code==400
    assert c.post('/api/store/quote',headers=h,json=payload(items=[{'id':'sauce-cheese','quantity':1}],delivery_mode='delivery')).status_code==400

def test_order_contacts_encrypted_and_customer_isolation(shop):
    c,a,h,g=shop
    r=order(c,h,save_profile=True)
    assert r.status_code==201
    own=c.get('/api/store/profile').json
    assert own['orders'][0]['id']==r.json['order_id'] and own['orders'][0]['customer']['phone']=='+79990001111'
    with a.connect_db() as db:
        data=[dict(x) for x in db.execute('SELECT * FROM orders')]+[dict(x) for x in db.execute('SELECT * FROM shop_order_details')]+[dict(x) for x in db.execute('SELECT * FROM audit_log')]
        assert '+79990001111' not in json.dumps(data) and 'Синтетический покупатель' not in json.dumps(data,ensure_ascii=False)
    other=a.app.test_client();other.get('/api/store/profile')
    assert other.get('/api/store/profile',query_string={'guest_id':g}).json['orders']==[]
    assert other.get('/api/admin/store/orders').status_code==401

def test_stock_reservation_idempotency_and_cancel_release(shop):
    c,a,h,g=shop
    admin=admin_login(c)
    rows=c.get('/api/admin/store/inventory').json;p=next(p for p in rows if p['product_id']=='live-crayfish-standart-kg')
    ah={'X-CSRF-Token':admin}
    assert c.put('/api/admin/store/inventory/'+p['product_id'],headers=ah,json={'quantity':2,'tracked':True,'expected_quantity_milli':p['quantity_milli'],'reason':'Фактическая инвентаризация'}).status_code==200
    h={'X-CSRF-Token':c.get('/api/store/profile').json['csrf_token']}
    headers={**h,'Idempotency-Key':'same-shop-order-123456789'};body=payload(items=[{'id':p['product_id'],'quantity':1.5}])
    first=c.post('/api/store/orders',headers=headers,json=body);second=c.post('/api/store/orders',headers=headers,json=body)
    assert first.status_code==second.status_code==201 and first.json==second.json
    assert order(c,h,items=[{'id':p['product_id'],'quantity':1}]).status_code==409
    oid=first.json['order_id']
    assert c.patch('/api/admin/orders/'+oid,headers=ah,json={'status':'cancelled'}).status_code==200
    assert c.patch('/api/admin/orders/'+oid,headers=ah,json={'status':'cancelled'}).status_code==200
    with a.connect_db() as db:
        assert db.execute('SELECT quantity_milli FROM shop_inventory WHERE product_id=?',(p['product_id'],)).fetchone()[0]==2000
        assert db.execute('SELECT COUNT(*) FROM shop_stock_ledger WHERE reference=?',('release:'+oid,)).fetchone()[0]==1

def test_bonus_spend_cashback_and_refund_are_exact_and_snapshot_based(shop):
    c,a,h,g=shop;admin=admin_login(c);ah={'X-CSRF-Token':admin}
    assert c.patch('/api/admin/store/customers/'+g,headers={**ah,'Idempotency-Key':'manual-bonus-credit-123456'},json={'bonus_delta':1000,'reason':'Компенсация покупки'}).status_code==200
    h={'X-CSRF-Token':c.get('/api/store/profile').json['csrf_token']}
    assert order(c,h,bonus_spend=999).status_code==409
    first=order(c,h,bonus_spend=500);assert first.status_code==201
    assert first.json['total_rub']==3080 and first.json['bonus_earned']==154
    oid=first.json['order_id']
    assert c.put('/api/admin/store/settings',headers=ah,json={'cashback_percent':20}).status_code==200
    for _ in range(2):assert c.patch('/api/admin/orders/'+oid,headers=ah,json={'status':'paid'}).status_code==200
    assert c.get('/api/store/profile').json['balance']==654
    c.patch('/api/admin/orders/'+oid,headers=ah,json={'status':'cancelled'})
    assert c.get('/api/store/profile').json['balance']==1000

def test_registration_login_do_not_grant_staff_and_preserve_orders(shop):
    c,a,h,g=shop;oid=order(c,h).json['order_id']
    credentials={'email':'synthetic@example.invalid','password':'synthetic-safe-password-123'}
    assert c.post('/api/store/auth/register',headers=h,json=credentials).status_code==201
    assert c.get('/api/admin/store/customers').status_code==401
    other=a.app.test_client();profile=other.get('/api/store/profile').json;oh={'X-CSRF-Token':profile['csrf_token']}
    assert other.post('/api/store/auth/login',headers=oh,json=credentials).status_code==200
    assert other.get('/api/store/profile').json['orders'][0]['id']==oid
    assert other.get('/api/admin/store/customers').status_code==401
    assert other.post('/api/store/auth/logout',headers=oh,json={}).status_code==200
    assert other.get('/api/store/profile').json['orders']==[]

def test_notifications_are_internal_and_external_dispatch_is_explicitly_configured(shop,monkeypatch):
    c,a,h,g=shop;calls=[];monkeypatch.setattr(a.connections,'deliver',lambda *args:calls.append(args) or {'remote_id':'synthetic-message-id'})
    assert order(c,h).status_code==201 and calls==[]
    admin=admin_login(c);ah={'X-CSRF-Token':admin}
    assert len(c.get('/api/admin/store/notifications').json['notifications'])==1
    assert c.put('/api/admin/store/settings',headers=ah,json={'notification_channels':['max']}).status_code==200
    assert order(c,h).status_code==201 and len(calls)==1
    assert '+79990001111' not in calls[0][1]
    assert c.post('/api/admin/store/notifications/dispatch',headers=ah,json={}).json==[]

def test_hidden_staff_entry_and_customer_access_are_distinct(shop,monkeypatch):
    c,a,h,g=shop;monkeypatch.setenv('HIDE_STAFF_ENTRY','true')
    assert c.get('/admin/login').status_code==404
    assert c.get('/admin').status_code==404
    page=c.get('/team/rakovar-control/login');assert page.status_code==200
    with c.session_transaction() as s:csrf=s['admin_csrf']
    assert c.post('/team/rakovar-control/login',data={'password':'test-admin-password','csrf_token':csrf}).status_code==302
    assert c.get('/admin').status_code==200
    assert c.get('/account').status_code==200

def test_admin_can_edit_full_promotion_and_reject_invalid_dates(shop):
    c,a,h,g=shop;admin=admin_login(c);ah={'X-CSRF-Token':admin}
    assert c.patch('/api/admin/promotions/WELCOME10',headers=ah,json={'title':'Новая акция','description':'Точные условия','discount_type':'fixed','discount_value':250,'min_order':2000,'max_uses':40,'starts_at':'2026-01-01','ends_at':'2027-01-01','ticket_reward':2}).status_code==200
    assert c.patch('/api/admin/promotions/WELCOME10',headers=ah,json={'ends_at':'2025-01-01'}).status_code==400
    row=next(x for x in c.get('/api/admin/promotions').json if x['code']=='WELCOME10')
    assert row['discount_value']==250 and row['max_uses']==40

def test_quote_and_order_reject_csrf_and_contactless_delivery(shop):
    c,a,h,g=shop
    assert c.post('/api/store/orders',json=payload()).status_code==400
    assert order(c,h,delivery_mode='delivery',address='').status_code==400
    assert c.post('/api/store/orders',headers=h,json=payload()).status_code==428

def test_free_demo_game_points_do_not_become_checkout_money(shop):
    c,a,h,g=shop
    with a.connect_db() as db:db.execute('UPDATE visitors SET points=10000 WHERE guest_id=?',(g,))
    assert c.get('/api/store/profile').json['balance']==0
    assert order(c,h,bonus_spend=10).status_code==409

def test_owned_prize_delivery_and_gift_are_reserved_and_refunded(shop):
    c,a,h,g=shop
    with a.connect_db() as db:
        db.execute("INSERT INTO spins(guest_id,prize_id,prize_title,redemption_code,created_at) VALUES(?,?,?,?,?)",(g,'prize-delivery','Доставка','RK-DELIVERY-TEST',a.NOW()))
        db.execute("INSERT INTO spins(guest_id,prize_id,prize_title,redemption_code,created_at) VALUES(?,?,?,?,?)",(g,'prize-sauce','Соус','RK-GIFT-TEST',a.NOW()))
    delivery=order(c,h,promo_code='RK-DELIVERY-TEST',delivery_mode='delivery',address='Синтетическая улица, дом 10')
    assert delivery.status_code==201 and delivery.json['total_rub']==3580
    assert order(c,h,promo_code='RK-DELIVERY-TEST',delivery_mode='delivery',address='Синтетическая улица, дом 10').status_code==409
    gift=order(c,h,promo_code='RK-GIFT-TEST')
    assert gift.status_code==201
    own=c.get('/api/store/profile').json
    assert any(i.get('gift') and i['line_total']==0 for o in own['orders'] if o['id']==gift.json['order_id'] for i in o['items'])
    other=a.app.test_client();oh={'X-CSRF-Token':other.get('/api/store/profile').json['csrf_token']}
    assert order(other,oh,promo_code='RK-GIFT-TEST').status_code==409
    admin=admin_login(c)
    assert c.patch('/api/admin/orders/'+gift.json['order_id'],headers={'X-CSRF-Token':admin},json={'status':'cancelled'}).status_code==200
    with a.connect_db() as db:assert db.execute("SELECT status FROM spins WHERE redemption_code='RK-GIFT-TEST'").fetchone()[0]=='unclaimed'

def test_inventory_optimistic_conflict_and_customer_bonus_replay(shop):
    c,a,h,g=shop;token=admin_login(c);ah={'X-CSRF-Token':token}
    p=next(x for x in c.get('/api/admin/store/inventory').json if x['product_id']=='crayfish-medium-kg')
    body={'quantity':3,'tracked':True,'expected_quantity_milli':p['quantity_milli'],'reason':'Пересчёт фактического остатка'}
    assert c.put('/api/admin/store/inventory/'+p['product_id'],headers=ah,json=body).status_code==200
    assert c.put('/api/admin/store/inventory/'+p['product_id'],headers=ah,json=body).status_code==409
    bh={**ah,'Idempotency-Key':'unique-customer-bonus-request-111'}
    for _ in range(2):assert c.patch('/api/admin/store/customers/'+g,headers=bh,json={'bonus_delta':200,'reason':'Компенсация'}).status_code==200
    assert c.patch('/api/admin/store/customers/'+g,headers=bh,json={'bonus_delta':300,'reason':'Компенсация'}).status_code==409
    assert c.get('/api/store/profile').json['balance']==200

def test_uploaded_photos_persist_in_database_and_cannot_be_html(shop):
    import base64
    from pathlib import Path
    c,a,h,g=shop;token=admin_login(c);ah={'X-CSRF-Token':token}
    original=(Path(__file__).parents[1]/'static/images/menu/live-company-0.jpg').read_bytes()
    body={'filename':'company-photo.jpg','mime_type':'image/jpeg','base64':base64.b64encode(original).decode()}
    first=c.post('/api/admin/store/media',headers=ah,json=body)
    assert first.status_code==201 and first.json['url'].startswith('/media/')
    assert c.post('/api/admin/store/media',headers=ah,json=body).json['id']==first.json['id']
    a.init_db()
    public=a.app.test_client().get(first.json['url'])
    assert public.status_code==200 and public.data==original and public.headers['X-Content-Type-Options']=='nosniff'
    assert 'immutable' in public.headers['Cache-Control']
    bad={**body,'base64':base64.b64encode(b'<script>alert(1)</script>').decode()}
    assert c.post('/api/admin/store/media',headers=ah,json=bad).status_code==400
    assert c.patch('/api/admin/products/crayfish-medium-kg',headers=ah,json={'image_url':first.json['url']}).status_code==200

def test_revoked_customer_session_cannot_fall_back_to_account_guest_cookie(shop):
    c,a,h,g=shop
    assert order(c,h).status_code==201
    assert c.post('/api/store/auth/register',headers=h,json={'email':'revoked@example.invalid','password':'synthetic-long-password-123'}).status_code==201
    with a.connect_db() as db:db.execute('DELETE FROM shop_sessions')
    profile=c.get('/api/store/profile').json
    assert profile['authenticated'] is False and profile['guest_id']!=g and profile['orders']==[]

def test_operator_photo_override_survives_seed_refresh_and_private_pages_are_not_cached(shop):
    c,a,h,g=shop;token=admin_login(c);ah={'X-CSRF-Token':token}
    photo='/static/images/menu/live-company-1.jpg'
    assert c.patch('/api/admin/products/crayfish-medium-kg',headers=ah,json={'image_url':photo,'description':'Оператор сохранил карточку'}).status_code==200
    with a.connect_db() as db:db.execute("UPDATE site_settings SET setting_value='old' WHERE setting_key='catalog_seed_version'")
    a.init_db()
    with a.connect_db() as db:
        row=db.execute("SELECT image_url,description FROM products WHERE id='crayfish-medium-kg'").fetchone()
        assert row['image_url']==photo and row['description']=='Оператор сохранил карточку'
    for path in ['/account','/team/rakovar-control/login']:
        response=c.get(path)
        assert response.headers['Cache-Control']=='no-store' and 'noindex' in response.headers['X-Robots-Tag']
    for path in ['/','/static/storefront.js','/static/shop.css']:
        assert c.get(path).headers['Cache-Control']=='no-cache'
