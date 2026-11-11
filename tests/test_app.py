import importlib
import hashlib
import json
import sys
import uuid
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from werkzeug.security import generate_password_hash

@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    monkeypatch.setenv('SQLITE_DB_PATH', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setenv('ADMIN_PASSWORD_HASH', generate_password_hash('test-admin-password'))
    if 'app' in sys.modules:
        module = importlib.reload(sys.modules['app'])
    else:
        module = importlib.import_module('app')
    module.DB_PATH = str(tmp_path / 'test.sqlite3')
    module.DEMO_MODE = True
    module.ADMIN_PASSWORD_HASH = generate_password_hash('test-admin-password')
    module.init_db()
    module.app.config.update(TESTING=True, SECRET_KEY='test-session-secret')
    return module

@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()

def bootstrap(client, guest='guest-test-identifier-12345'):
    response = client.get('/api/bootstrap', query_string={'guest_id': guest})
    assert response.status_code == 200
    return response.json['csrf_token']

def admin_login(client):
    page = client.get('/admin/login')
    assert page.status_code == 200
    with client.session_transaction() as sess:
        csrf = sess['admin_csrf']
    response = client.post('/admin/login', data={'password':'test-admin-password','csrf_token':csrf})
    assert response.status_code == 302
    with client.session_transaction() as sess:
        return sess['admin_csrf']

def test_health_and_demo_bootstrap(client):
    assert client.get('/api/health').json['mode'] == 'demo'
    data = client.get('/api/bootstrap', query_string={'guest_id':'guest-test-identifier-12345'}).json
    assert data['demo_mode'] is True
    assert len(data['products']) >= 5
    assert data['visitor']['tickets'] == 3


def test_pages_use_content_versioned_scripts_and_styles(client, app_module):
    class AssetLinks(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []

        def handle_starttag(self, tag, attributes):
            attrs = dict(attributes)
            if tag == 'script' and attrs.get('src', '').startswith('/static/'):
                self.urls.append(attrs['src'])
            if tag == 'link' and attrs.get('rel') == 'stylesheet' and attrs.get('href', '').startswith('/static/'):
                self.urls.append(attrs['href'])

    # Version URLs must also be present on the separately opened account and
    # staff pages; otherwise a returning browser can mix incompatible releases.
    for page in ('/', '/account', '/team/rakovar-control/login'):
        response = client.get(page)
        assert response.status_code == 200
        parser = AssetLinks()
        parser.feed(response.text)
        assert parser.urls
        for url in parser.urls:
            parts = urlsplit(url)
            filename = parts.path.removeprefix('/static/')
            expected = hashlib.sha256((app_module.BASE_DIR / 'static' / filename).read_bytes()).hexdigest()[:16]
            assert parse_qs(parts.query)['v'] == [expected]
            assert client.get(url).status_code == 200
        assert response.headers['Cache-Control'] in ('no-cache', 'no-store')

def test_quote_uses_server_prices_and_coupon(client):
    data = client.post('/api/checkout/quote', json={
        'items':[{'id':'crayfish-medium-kg','quantity':1,'price':1}],
        'promo_code':'WELCOME10','delivery_mode':'pickup'
    })
    assert data.status_code == 200
    assert data.json['subtotal_rub'] == 3580
    assert data.json['discount_rub'] == 358
    assert data.json['total_rub'] == 3222

def test_demo_order_discards_personal_data(client):
    csrf = bootstrap(client)
    response = client.post('/api/orders', headers={'X-CSRF-Token':csrf,'Idempotency-Key':uuid.uuid4().hex}, json={
        'guest_id':'guest-test-identifier-12345','items':[{'id':'crayfish-medium-kg','quantity':1}],
        'name':'Test User','phone':'+79990000000','consent':True,'delivery_mode':'pickup'
    })
    assert response.status_code == 201
    order = client.get('/api/admin/orders')
    assert order.status_code == 401
    token = admin_login(client)
    order = client.get('/api/admin/orders').json[0]
    assert order['contact_label'] == 'НЕ СОХРАНЕНО'
    assert order['customer_label'] == 'ДЕМО-ПОКУПАТЕЛЬ'
    assert '+79990000000' not in json.dumps(order)

def test_game_spin_is_server_side_and_consumes_ticket(client):
    csrf = bootstrap(client)
    guest='guest-test-identifier-12345'
    before=client.get('/api/game/profile',query_string={'guest_id':guest}).json['tickets']
    r=client.post('/api/game/spin',headers={'X-CSRF-Token':csrf,'Idempotency-Key':uuid.uuid4().hex},json={'guest_id':guest})
    assert r.status_code == 200
    assert r.json['tickets'] == before-1
    assert r.json['prize']['title']

def test_daily_ticket_is_disabled(client):
    csrf=bootstrap(client); guest='guest-test-identifier-12345'
    response=client.post('/api/game/daily-ticket',headers={'X-CSRF-Token':csrf},json={'guest_id':guest})
    assert response.status_code == 410
    assert response.json['error'] == 'ticket_rule_changed'

def test_contest_entry_prevents_duplicate(client):
    csrf=bootstrap(client); guest='guest-test-identifier-12345'
    payload={'guest_id':guest,'alias':'Тестовый участник','answer':'Люблю морские ужины'}
    first=client.post('/api/contests/sea-evening/entries',headers={'X-CSRF-Token':csrf},json=payload)
    second=client.post('/api/contests/sea-evening/entries',headers={'X-CSRF-Token':csrf},json=payload)
    assert first.status_code == 201 and second.status_code == 409

def test_admin_product_and_promo_crud(client):
    csrf=admin_login(client); headers={'X-CSRF-Token':csrf}
    product=client.post('/api/admin/products',headers=headers,json={'title':'Тестовый продукт','category':'Тест','price':1000,'stock':2,'image':'opt_hero.svg'})
    assert product.status_code == 201
    promo=client.post('/api/admin/promotions',headers=headers,json={'code':'TEST20','title':'Тестовая акция','discount_type':'percent','discount_value':20,'min_order':100})
    assert promo.status_code == 201
    assert client.get('/api/admin/dashboard').status_code == 200

def test_social_publish_is_not_faked(client, monkeypatch):
    csrf=admin_login(client); headers={'X-CSRF-Token':csrf}
    post=client.post('/api/admin/content',headers=headers,json={'title':'Тест','body':'Тестовый пост','channels':['vk'],'status':'draft'})
    assert post.status_code == 201
    response=client.post(f"/api/admin/content/{post.json['id']}/publish",headers=headers,json={})
    assert response.status_code == 409
    assert response.json['error'] == 'content_approval_required'

def test_admin_apis_require_auth(client):
    assert client.get('/api/admin/dashboard').status_code == 401
    assert client.post('/api/admin/products',json={}).status_code == 401

def test_contest_draw_is_persisted(client, app_module):
    with app_module.connect_db() as c:
        c.execute("UPDATE contests SET ends_at=? WHERE id='sea-evening'", (app_module.TODAY(),))
    guest = 'guest-contest-test-123456'
    csrf = bootstrap(client, guest)
    entry = client.post('/api/contests/sea-evening/entries', headers={'X-CSRF-Token':csrf}, json={
        'guest_id':guest,'alias':'Участник демо','answer':'Мой идеальный морской вечер'
    })
    assert entry.status_code == 201
    with app_module.connect_db() as c:
        yesterday = (app_module.dt.date.fromisoformat(app_module.TODAY()) - app_module.dt.timedelta(days=1)).isoformat()
        c.execute("UPDATE contests SET ends_at=? WHERE id='sea-evening'", (yesterday,))
    admin_csrf = admin_login(client)
    draw = client.post('/api/admin/contests/sea-evening/draw', headers={'X-CSRF-Token':admin_csrf}, json={'winners':1})
    assert draw.status_code == 200
    contests = client.get('/api/admin/contests').json
    contest = next(x for x in contests if x['id']=='sea-evening')
    assert contest['status'] == 'drawn'
    assert contest['winners'][0]['alias'] == 'Участник демо'

def test_public_mutations_require_csrf(client):
    response = client.post('/api/game/spin', json={'guest_id':'guest-test-identifier-12345'})
    assert response.status_code == 400




def test_ticket_only_promotion_awards_tickets_after_payment(client):
    token=admin_login(client); headers={'X-CSRF-Token':token}
    created=client.post('/api/admin/promotions',headers=headers,json={
        'code':'TICKETSONLY','title':'Билеты за заказ','discount_type':'fixed',
        'discount_value':0,'min_order':0,'max_uses':5,'ticket_reward':2
    })
    assert created.status_code==201
    guest='guest-ticket-promo-12345'
    csrf=bootstrap(client,guest)
    order=client.post('/api/orders',headers={'X-CSRF-Token':csrf,'Idempotency-Key':uuid.uuid4().hex},json={
        'guest_id':guest,'items':[{'id':'crayfish-medium-kg','quantity':1}],
        'name':'Test User','phone':'+79990000000','consent':True,'delivery_mode':'pickup','promo_code':'TICKETSONLY'
    })
    assert order.status_code==201
    admin_csrf=admin_login(client); headers={'X-CSRF-Token':admin_csrf}
    paid=client.patch(f"/api/admin/orders/{order.json['order_id']}",headers=headers,json={'status':'paid'})
    assert paid.json['tickets_awarded']==5

def test_admin_can_change_loyalty_rate_and_order_uses_it(client):
    token=admin_login(client); headers={'X-CSRF-Token':token}
    updated=client.patch('/api/admin/loyalty/rules',headers=headers,json={'rub_per_ticket':500})
    assert updated.status_code==200 and updated.json['rub_per_ticket']==500
    guest='guest-custom-loyalty-12345'
    csrf=bootstrap(client,guest)
    order=client.post('/api/orders',headers={'X-CSRF-Token':csrf,'Idempotency-Key':uuid.uuid4().hex},json={
        'guest_id':guest,'items':[{'id':'crayfish-medium-kg','quantity':1}],
        'name':'Test User','phone':'+79990000000','consent':True,'delivery_mode':'pickup'
    })
    admin_csrf=admin_login(client); headers={'X-CSRF-Token':admin_csrf}
    paid=client.patch(f"/api/admin/orders/{order.json['order_id']}",headers=headers,json={'status':'paid'})
    assert paid.json['tickets_awarded']==7

def test_admin_can_edit_prize_weight_and_contest_ticket_reward(client):
    token=admin_login(client); headers={'X-CSRF-Token':token}
    prizes=client.get('/api/admin/prizes').json
    prize_id=prizes[0]['id']
    updated=client.patch(f'/api/admin/prizes/{prize_id}',headers=headers,json={'weight':77,'stock':9,'partner':'Тестовый партнёр'})
    assert updated.status_code==200
    contests=client.get('/api/admin/contests').json
    contest_id=contests[0]['id']
    contest=client.patch(f'/api/admin/contests/{contest_id}',headers=headers,json={'ticket_reward':2,'status':'paused'})
    assert contest.status_code==200
    refreshed=client.get('/api/admin/contests').json
    current=next(x for x in refreshed if x['id']==contest_id)
    assert current['ticket_reward']==2 and current['status']=='paused'


def test_admin_can_confirm_price_and_stock(client):
    token=admin_login(client); headers={'X-CSRF-Token':token}
    updated=client.patch('/api/admin/products/crayfish-medium-kg',headers=headers,json={'price_verified':1,'stock_confirmed':1,'stock':12})
    assert updated.status_code==200
    rows=client.get('/api/admin/products').json
    product=next(x for x in rows if x['id']=='crayfish-medium-kg')
    assert product['price_verified']==1 and product['stock_confirmed']==1 and product['stock']==12

def test_paid_demo_order_awards_tickets_once(client, app_module):
    guest='guest-paid-order-123456'
    csrf=bootstrap(client,guest)
    order=client.post('/api/orders',headers={'X-CSRF-Token':csrf,'Idempotency-Key':uuid.uuid4().hex},json={
        'guest_id':guest,'items':[{'id':'crayfish-medium-kg','quantity':1}],
        'name':'Test User','phone':'+79990000000','consent':True,'delivery_mode':'pickup'
    })
    assert order.status_code == 201
    admin_csrf=admin_login(client)
    headers={'X-CSRF-Token':admin_csrf}
    first=client.patch(f"/api/admin/orders/{order.json['order_id']}",headers=headers,json={'status':'paid'})
    second=client.patch(f"/api/admin/orders/{order.json['order_id']}",headers=headers,json={'status':'paid'})
    assert first.status_code == 200 and first.json['tickets_awarded'] == 3
    assert second.status_code == 200 and second.json['tickets_awarded'] == 0
    balance=client.get('/api/game/profile',query_string={'guest_id':guest}).json['tickets']
    assert balance == 6



def test_inquiry_only_product_cannot_be_added_to_cart(client):
    response=client.post('/api/checkout/quote',json={
        'items':[{'id':'edible-bouquet-request','quantity':1}],
        'delivery_mode':'pickup'
    })
    assert response.status_code == 409
    assert response.json['message'] == 'price_on_request'


def test_paid_order_cancellation_reverses_ticket_ledger(client):
    guest='guest-refund-order-123456'
    csrf=bootstrap(client,guest)
    order=client.post('/api/orders',headers={'X-CSRF-Token':csrf,'Idempotency-Key':uuid.uuid4().hex},json={
        'guest_id':guest,'items':[{'id':'crayfish-medium-kg','quantity':1}],
        'name':'Test User','phone':'+79990000000','consent':True,'delivery_mode':'pickup'
    })
    assert order.status_code == 201
    admin_csrf=admin_login(client); headers={'X-CSRF-Token':admin_csrf}
    paid=client.patch(f"/api/admin/orders/{order.json['order_id']}",headers=headers,json={'status':'paid'})
    cancelled=client.patch(f"/api/admin/orders/{order.json['order_id']}",headers=headers,json={'status':'cancelled'})
    reopened=client.patch(f"/api/admin/orders/{order.json['order_id']}",headers=headers,json={'status':'paid'})
    assert paid.json['tickets_awarded']==3
    assert cancelled.json['tickets_reversed']==3
    assert reopened.status_code==409
    balance=client.get('/api/game/profile',query_string={'guest_id':guest}).json['tickets']
    assert balance==3

def test_max_init_data_is_verified_and_identity_is_bound(client, app_module):
    import hashlib, hmac, time
    from urllib.parse import quote
    token='local-test-token'
    app_module.MAX_BOT_TOKEN=token
    params={
        'auth_date':str(int(time.time())),
        'user':json.dumps({'id':123456789012345,'first_name':'MAX Test'},ensure_ascii=False,separators=(',',':')),
    }
    data_check='\n'.join(f"{k}={params[k]}" for k in sorted(params))
    secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    params['hash']=hmac.new(secret,data_check.encode(),hashlib.sha256).hexdigest()
    raw='&'.join(f'{k}={quote(v, safe="")}' for k,v in params.items())
    response=client.post('/api/max/auth',json={'init_data':raw})
    assert response.status_code == 200
    assert response.json['guest_id']=='max_123456789012345'
    boot=client.get('/api/bootstrap',query_string={'guest_id':'guest-attacker-id-12345'})
    assert boot.status_code == 200
    assert boot.json['visitor']['guest_id']=='max_123456789012345'


def test_max_init_data_rejects_bad_signature(client, app_module):
    import time
    from urllib.parse import quote
    app_module.MAX_BOT_TOKEN='local-test-token'
    values={'auth_date':str(int(time.time())),'user':json.dumps({'id':123456789012345}),'hash':'0'*64}
    raw='&'.join(f'{k}={quote(v, safe="")}' for k,v in values.items())
    response=client.post('/api/max/auth',json={'init_data':raw})
    assert response.status_code == 403


def test_anonymous_visitor_id_is_session_bound(client):
    csrf=bootstrap(client,'guest-session-owner-12345')
    response=client.get('/api/game/profile',query_string={'guest_id':'guest-attacker-123456'})
    assert response.status_code == 403

def test_admin_can_edit_storefront_copy(client):
    csrf = admin_login(client)
    response = client.put('/api/admin/settings', headers={'X-CSRF-Token':csrf}, json={
        'hero_title':'Новый заголовок витрины','hero_cta':'Смотреть каталог'
    })
    assert response.status_code == 200
    guest='guest-settings-test-12345'
    settings=client.get('/api/bootstrap',query_string={'guest_id':guest}).json['settings']
    assert settings['hero_title']=='Новый заголовок витрины'
    assert settings['hero_cta']=='Смотреть каталог'


def test_referral_rewards_both_sides_only_after_first_paid_order(app_module):
    referrer_client = app_module.app.test_client()
    friend_client = app_module.app.test_client()
    referrer = 'guest-referrer-test-12345'
    friend = 'guest-friend-test-123456'
    referrer_csrf = bootstrap(referrer_client, referrer)
    friend_csrf = bootstrap(friend_client, friend)
    profile = referrer_client.get('/api/referrals/profile', query_string={'guest_id': referrer})
    code = profile.json['code']
    attached = friend_client.post('/api/referrals/attach', headers={'X-CSRF-Token': friend_csrf}, json={'guest_id': friend, 'code': code})
    assert attached.status_code == 201
    duplicate = friend_client.post('/api/referrals/attach', headers={'X-CSRF-Token': friend_csrf}, json={'guest_id': friend, 'code': code})
    assert duplicate.status_code == 409
    order = friend_client.post('/api/orders', headers={'X-CSRF-Token': friend_csrf, 'Idempotency-Key': uuid.uuid4().hex}, json={
        'guest_id': friend, 'items': [{'id':'crayfish-medium-kg','quantity':1}],
        'name':'Test User', 'phone':'+79990000000', 'consent':True, 'delivery_mode':'pickup'
    })
    assert order.status_code == 201
    admin_client = app_module.app.test_client()
    admin_csrf = admin_login(admin_client)
    paid = admin_client.patch(f"/api/admin/orders/{order.json['order_id']}", headers={'X-CSRF-Token':admin_csrf}, json={'status':'paid'})
    assert paid.status_code == 200
    referrer_balance = referrer_client.get('/api/game/profile', query_string={'guest_id':referrer}).json['tickets']
    friend_balance = friend_client.get('/api/game/profile', query_string={'guest_id':friend}).json['tickets']
    assert referrer_balance == 13  # 3 demo tickets + 10 referral tickets
    assert friend_balance == 11  # 3 demo + 3 purchase + 5 friend tickets
    admin_referrals = admin_client.get('/api/admin/referrals')
    assert admin_referrals.status_code == 200
    assert admin_referrals.json['qualified'] == 1


def test_referral_bonus_is_reversed_when_qualifying_order_is_cancelled(app_module):
    referrer_client = app_module.app.test_client()
    friend_client = app_module.app.test_client()
    referrer = 'guest-referrer-cancel-12345'
    friend = 'guest-friend-cancel-123456'
    bootstrap(referrer_client, referrer)
    friend_csrf = bootstrap(friend_client, friend)
    code = referrer_client.get('/api/referrals/profile', query_string={'guest_id':referrer}).json['code']
    assert friend_client.post('/api/referrals/attach', headers={'X-CSRF-Token':friend_csrf}, json={'guest_id':friend,'code':code}).status_code == 201
    order = friend_client.post('/api/orders', headers={'X-CSRF-Token':friend_csrf,'Idempotency-Key':uuid.uuid4().hex}, json={
        'guest_id':friend,'items':[{'id':'crayfish-medium-kg','quantity':1}],
        'name':'Test User','phone':'+79990000000','consent':True,'delivery_mode':'pickup'
    })
    admin_client = app_module.app.test_client(); admin_csrf=admin_login(admin_client); headers={'X-CSRF-Token':admin_csrf}
    admin_client.patch(f"/api/admin/orders/{order.json['order_id']}",headers=headers,json={'status':'paid'})
    cancelled=admin_client.patch(f"/api/admin/orders/{order.json['order_id']}",headers=headers,json={'status':'cancelled'})
    assert cancelled.status_code == 200
    assert cancelled.json['tickets_reversed'] == 18  # 3 purchase + 10 inviter + 5 friend
    assert referrer_client.get('/api/game/profile',query_string={'guest_id':referrer}).json['tickets'] == 3
    assert friend_client.get('/api/game/profile',query_string={'guest_id':friend}).json['tickets'] == 3



def test_admin_can_edit_referral_rewards_and_tier_thresholds(client):
    token=admin_login(client)
    response=client.patch('/api/admin/referrals/rules',headers={'X-CSRF-Token':token},json={
        'minimum_order_rub':2000,'referrer_tickets':12,'friend_tickets':6,
        'tier_sailor_rub':6000,'tier_captain_rub':18000,'tier_admiral_rub':50000
    })
    assert response.status_code==200
    assert response.json['tier_admiral_rub']==50000
    invalid=client.patch('/api/admin/referrals/rules',headers={'X-CSRF-Token':token},json={
        'minimum_order_rub':2000,'referrer_tickets':12,'friend_tickets':6,
        'tier_sailor_rub':18000,'tier_captain_rub':6000,'tier_admiral_rub':50000
    })
    assert invalid.status_code==400
