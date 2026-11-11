"""Store checkout, customer accounts, inventory and bonus operations.

All money, stock, receipts and bonuses are computed in server transactions.
Customer contacts are encrypted; notification payloads contain no contacts.
"""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import time
from decimal import Decimal, InvalidOperation

from flask import abort, jsonify, request, session, render_template, Response
from werkzeug.security import check_password_hash, generate_password_hash
from commerce_safety import request_receipt, save_receipt
from connections import ConnectionError

DEFAULTS = {
    'accepting_orders': True, 'delivery_fee': 350, 'delivery_minimum': 1000,
    'free_delivery_from': 5000, 'cashback_percent': 5, 'bonus_spend_percent': 20,
    'loyalty_enabled': True, 'welcome_bonus': 0, 'notification_channels': [],
    'order_comment': 'Оплата при получении. Оператор подтвердит время и способ оплаты.',
    'builder_enabled': True, 'contests_visible': False, 'catalog_page_size': 24,
    'gift_mappings': {'prize-sauce':'sauce-creamy-garlic'},
}
STATUS = {'received':'Новый','demo_received':'Новый','confirmed':'Подтверждён','paid':'Оплачен',
          'preparing':'Готовится','ready':'Готов к выдаче','completed':'Завершён','cancelled':'Отменён'}


class Store:
    def __init__(self, module):
        self.a = module
        self.app = module.app
        self.db = module.connect_db

    def now(self):
        return self.a.NOW()

    def encrypt(self, data):
        return self.a.connections.cipher().encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()

    def decrypt(self, text):
        return json.loads(self.a.connections.cipher().decrypt(text.encode())) if text else {}

    def settings(self, c):
        row = c.execute("SELECT setting_value FROM site_settings WHERE setting_key='store_operations'").fetchone()
        return {**DEFAULTS, **(json.loads(row[0]) if row else {})}

    def principal_can(self, permission):
        principal = self.a.staff_access.current_principal() or {}
        return '*' in principal.get('permissions', []) or permission in principal.get('permissions', [])

    def identity(self):
        token = session.get('customer_token', '')
        if token:
            with self.db() as c:
                row = c.execute('SELECT a.guest_id FROM shop_sessions s JOIN shop_accounts a ON a.id=s.account_id WHERE s.token_hash=? AND s.expires_at>?',
                                (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
            if row:
                session['guest_id'] = row[0]
                return row[0], True
            session.pop('customer_token', None)
        guest = session.get('max_guest_id') or session.get('guest_id')
        if guest and not session.get('max_guest_id'):
            with self.db() as c:owned=c.execute('SELECT 1 FROM shop_accounts WHERE guest_id=?',(guest,)).fetchone()
            if owned:
                session.pop('guest_id',None)
                guest=None
        if not guest:
            guest = self.a.resolve_guest_id(secrets.token_hex(24))
        return guest, bool(session.get('max_guest_id'))

    def ensure_profile(self, c, guest):
        self.a.get_visitor(c, guest)
        c.execute('INSERT INTO shop_profiles(guest_id,created_at,updated_at) VALUES(?,?,?) ON CONFLICT(guest_id) DO NOTHING', (guest,self.now(),self.now()))
        return c.execute('SELECT * FROM shop_profiles WHERE guest_id=?', (guest,)).fetchone()

    def inventory(self, c, product):
        step = 500 if 'кг' in product['unit'] else 1000
        c.execute('INSERT INTO shop_inventory(product_id,quantity_milli,step_milli,updated_at) VALUES(?,?,?,?) ON CONFLICT(product_id) DO NOTHING',
                  (product['id'], product['stock']*1000, step, self.now()))
        return c.execute('SELECT * FROM shop_inventory WHERE product_id=?', (product['id'],)).fetchone()

    def catalog(self, c):
        result=[]
        for product in self.a.public_catalog_products(c):
            if product['price_on_request'] or product['price']<=0 or (product['image'].endswith('.svg') and not product.get('image_url')):
                continue  # Unpriced drafts stay in the staff catalog, never become VK purchase links.
            inv=self.inventory(c,product)
            product.update(quantity_step=inv['step_milli']/1000, stock_tracked=bool(inv['tracked']),
                           available_quantity=(inv['quantity_milli']//inv['step_milli'])*inv['step_milli']/1000 if inv['tracked'] else 50,
                           availability='В наличии' if inv['tracked'] and inv['quantity_milli']>0 else 'Нет в наличии' if inv['tracked'] else 'Под заказ')
            product['stock']=product['available_quantity']
            result.append(product)
        return result

    def bonus_balance(self,c,guest):
        return int(c.execute('SELECT COALESCE(SUM(delta),0) FROM shop_bonus_ledger WHERE guest_id=?',(guest,)).fetchone()[0])

    def quote(self, c, data, guest):
        rules=self.settings(c)
        lines=data.get('items')
        if not isinstance(lines,list) or not 1<=len(lines)<=30:abort(400,description='invalid_cart')
        items=[];seen=set();subtotal=0
        for item in lines:
            if not isinstance(item,dict):abort(400,description='invalid_cart_item')
            pid=str(item.get('id',''))
            if pid in seen:abort(400,description='duplicate_cart_item')
            seen.add(pid)
            value=item.get('quantity')
            try:
                if isinstance(value,bool):raise ValueError()
                quantity=Decimal(str(value)); milli=int(quantity*1000)
                if not quantity.is_finite() or quantity*1000!=milli:raise ValueError()
            except (InvalidOperation,ValueError,OverflowError):abort(400,description='invalid_quantity')
            p=c.execute('SELECT * FROM products WHERE id=? AND active=1',(pid,)).fetchone()
            if not p or p['price_on_request'] or p['price']<=0 or self.a.is_non_brand_product(dict(p)):abort(409,description='item_unavailable')
            inv=self.inventory(c,p)
            if milli<inv['step_milli'] or milli>50000 or milli%inv['step_milli']:abort(400,description='invalid_quantity_step')
            if inv['tracked'] and inv['quantity_milli']<milli:abort(409,description='insufficient_stock')
            line=(p['price']*milli+500)//1000;subtotal+=line
            items.append({'id':pid,'title':p['title'],'quantity':milli/1000,'quantity_milli':milli,'unit_price':p['price'],'line_total':line,'unit':p['unit'],'reserved_milli':milli if inv['tracked'] else 0})
        code=str(data.get('promo_code','')).strip().upper()
        discount,message=self.a.discount_for(c,code,subtotal)
        promo=self.a.eligible_promotion(c,code,subtotal)
        if code.startswith('RK-') and not c.execute('SELECT 1 FROM spins WHERE guest_id=? AND redemption_code=?',(guest,code)).fetchone():
            promo=None;discount=0;message='Персональный код недоступен этому профилю'
        reward=None
        if code.startswith('RK-'):
            reward=c.execute('SELECT s.id,s.status,p.id AS prize_id,p.kind FROM spins s JOIN prizes p ON p.id=s.prize_id WHERE s.guest_id=? AND s.redemption_code=?',(guest,code)).fetchone()
            if reward and reward['status']!='unclaimed':abort(409,description='reward_already_used')
        delivery_mode=data.get('delivery_mode','pickup')
        if delivery_mode not in ('pickup','delivery'):abort(400,description='invalid_delivery_mode')
        if delivery_mode=='delivery' and subtotal<rules['delivery_minimum']:abort(400,description='delivery_min_order')
        fee=rules['delivery_fee'] if delivery_mode=='delivery' and (not rules['free_delivery_from'] or subtotal<rules['free_delivery_from']) else 0
        reward_id=None
        if reward and reward['kind']=='delivery':
            if delivery_mode!='delivery':abort(409,description='delivery_reward_requires_delivery')
            fee=0;message='Бесплатная доставка по вашему подарочному коду';reward_id=reward['id']
        if reward and reward['kind']=='gift':
            pid=rules['gift_mappings'].get(reward['prize_id'])
            p=c.execute('SELECT * FROM products WHERE id=? AND active=1',(pid,)).fetchone() if pid else None
            if not p:abort(409,description='gift_not_configured')
            inv=self.inventory(c,p)
            needed=1000+sum(i['quantity_milli'] for i in items if i['id']==pid)
            if inv['tracked'] and inv['quantity_milli']<needed:abort(409,description='gift_out_of_stock')
            items.append({'id':pid,'title':p['title']+' · подарок','quantity':1,'quantity_milli':1000,'unit_price':0,'line_total':0,'unit':p['unit'],'reserved_milli':1000 if inv['tracked'] else 0,'gift':True})
            message='Подарок добавлен к заказу';reward_id=reward['id']
        if reward and reward['kind']=='coupon' and promo:reward_id=reward['id']
        visitor=self.a.get_visitor(c,guest)
        try:
            points=data.get('bonus_spend',0)
            if isinstance(points,bool) or int(points)!=points:raise ValueError()
            points=int(points)
        except (TypeError,ValueError):abort(400,description='invalid_bonus_amount')
        max_points=min(max(0,self.bonus_balance(c,guest)),max(0,subtotal-discount)*rules['bonus_spend_percent']//100) if rules['loyalty_enabled'] else 0
        if points<0 or points>max_points:abort(409,description='bonus_limit_exceeded')
        total=max(0,subtotal-discount-points+fee)
        earned=max(0,subtotal-discount-points)*rules['cashback_percent']//100 if rules['loyalty_enabled'] else 0
        return {'items':items,'subtotal_rub':subtotal,'discount_rub':discount,'delivery_rub':fee,'total_rub':total,
                'promo_valid':bool(promo or reward_id),'reward_spin_id':reward_id,'promo_message':message,'promo_code':code if promo else '',
                'bonus_spent':points,'bonus_available':max(0,self.bonus_balance(c,guest)),'bonus_max':max_points,'bonus_earned':earned,
                'delivery_status':'fixed','delivery_finalized':True,'rules':rules}

    def bonus(self,c,guest,delta,reason,reference):
        if c.execute('SELECT 1 FROM shop_bonus_ledger WHERE reference=?',(reference,)).fetchone():return False
        self.a.get_visitor(c,guest)
        c.execute('INSERT INTO shop_bonus_ledger(id,guest_id,delta,reason,reference,created_at) VALUES(?,?,?,?,?,?)',
                  (secrets.token_hex(16),guest,delta,reason,reference,self.now()))
        c.execute('UPDATE visitors SET points=points+? WHERE guest_id=?',(delta,guest))
        return True

    def notice(self,c,guest,order_id,audience,kind,title,body):
        c.execute('INSERT INTO shop_notifications(id,guest_id,order_id,audience,kind,title,body,created_at) VALUES(?,?,?,?,?,?,?,?)',
                  (secrets.token_hex(16),guest,order_id,audience,kind,title,body,self.now()))

    def after_status(self,c,order,previous,status):
        detail=c.execute('SELECT * FROM shop_order_details WHERE order_id=?',(order['id'],)).fetchone()
        if not detail:return
        guest=order['guest_id'];oid=order['id']
        if status in ('paid','completed'):
            earned=int(json.loads(detail['rules_json']).get('bonus_earned',0))
            if earned and self.bonus(c,guest,earned,'Бонусы за заказ '+oid,'earn:'+oid):
                c.execute('UPDATE shop_order_details SET bonus_earned=? WHERE order_id=?',(earned,oid))
        if status=='cancelled' and not detail['inventory_released']:
            restored={}
            for item in json.loads(order['items_json']):
                if item.get('reserved_milli'):restored[item['id']]=restored.get(item['id'],0)+item['reserved_milli']
            for pid,milli in restored.items():
                c.execute('UPDATE shop_inventory SET quantity_milli=quantity_milli+?,updated_at=? WHERE product_id=?',(milli,self.now(),pid))
                c.execute('INSERT INTO shop_stock_ledger(id,product_id,delta_milli,reason,reference,actor,created_at) VALUES(?,?,?,?,?,?,?)',
                          (secrets.token_hex(16),pid,milli,'Возврат отменённого заказа','release:'+oid,self.a.staff_access.actor(),self.now()))
            if detail['bonus_spent']:self.bonus(c,guest,detail['bonus_spent'],'Возврат бонусов при отмене','refund:'+oid)
            if detail['bonus_earned']:self.bonus(c,guest,-detail['bonus_earned'],'Отмена начисления за заказ','reverse:'+oid)
            if order['promo_code']:c.execute('UPDATE promotions SET uses=CASE WHEN uses>0 THEN uses-1 ELSE 0 END WHERE code=?',(order['promo_code'],))
            c.execute('UPDATE shop_order_details SET inventory_released=1 WHERE order_id=?',(oid,))
        reward_id=json.loads(detail['rules_json']).get('reward_spin_id')
        if reward_id is not None and status in ('completed','cancelled'):
            c.execute('UPDATE spins SET status=? WHERE id=?',('unclaimed' if status=='cancelled' else 'claimed',reward_id))
        self.notice(c,guest,oid,'customer','order_status','Заказ '+oid,STATUS.get(status,status))
        self.notice(c,'',oid,'staff','order_status','Обновлён заказ '+oid,STATUS.get(status,status))

    def private_orders(self,c,guest=None,staff=False):
        where='WHERE o.guest_id=?' if guest else ''
        rows=c.execute('SELECT o.*,d.ciphertext,d.payment_method,d.bonus_spent,d.bonus_earned FROM orders o JOIN shop_order_details d ON d.order_id=o.id '+where+' ORDER BY o.created_at DESC LIMIT 200',(guest,) if guest else ()).fetchall()
        result=[]
        for row in rows:
            p=dict(row);secret=p.pop('ciphertext');p['items']=json.loads(p['items_json']);p['status_label']=STATUS.get(p['status'],p['status'])
            if not staff or self.principal_can('customers.read'):p['customer']=self.decrypt(secret)
            p['history']=[dict(r) for r in c.execute('SELECT new_status,created_at FROM order_status_history WHERE order_id=? ORDER BY created_at,id',(p['id'],))]
            result.append(p)
        return result

    def flush_notifications(self):
        # An actual order, never a credential check, queues a contact-free message.
        with self.db() as c:pending=[dict(r) for r in c.execute("SELECT * FROM shop_outbox WHERE state='pending' ORDER BY created_at LIMIT 20")]
        results=[]
        for row in pending:
            with self.db() as c:
                claimed=c.execute("UPDATE shop_outbox SET state='sending' WHERE id=? AND state='pending'",(row['id'],)).rowcount
            if not claimed:continue
            try:
                response=self.a.connections.deliver(row['provider'],row['body'],row['id'])
                state,remote,error='sent',response['remote_id'],''
            except ConnectionError as exc:
                state,remote,error='review','',getattr(exc,'code','delivery_not_confirmed')
            with self.db() as c:c.execute('UPDATE shop_outbox SET state=?,remote_id=?,error_code=? WHERE id=?',(state,remote,error,row['id']))
            results.append({'id':row['id'],'state':state,'remote_id':remote,'error':error})
        return results

    def register(self):
        app=self.app;a=self.a
        def route(path, endpoint, fn, methods=('GET',), permission=None):
            if permission:
                from staff_auth import ENDPOINT_PERMISSIONS
                ENDPOINT_PERMISSIONS[endpoint]=permission
            def wrapped(**kwargs):
                if request.method!='GET':
                    a.require_csrf()
                    if not isinstance(request.get_json(silent=True),dict):abort(400,description='invalid_json')
                return fn(**kwargs)
            wrapped.__name__=endpoint
            app.add_url_rule(path,endpoint,a.admin_required(wrapped) if permission else wrapped,methods=list(methods))

        @app.get('/media/<asset_id>')
        def store_media_public(asset_id):
            if not re.fullmatch(r'[a-f0-9]{32}',asset_id):abort(404)
            with self.db() as c:row=c.execute('SELECT mime_type,content_base64,sha256 FROM shop_media WHERE id=?',(asset_id,)).fetchone()
            if not row:abort(404)
            response=Response(base64.b64decode(row['content_base64']),mimetype=row['mime_type'])
            response.headers['X-Content-Type-Options']='nosniff'
            response.headers['Cache-Control']='public, max-age=31536000, immutable'
            response.set_etag(row['sha256'])
            return response.make_conditional(request)

        def upload_media():
            d=request.get_json();content=d.get('base64');mime=d.get('mime_type');name=str(d.get('filename','photo'))[:100]
            if not isinstance(content,str) or mime not in ('image/jpeg','image/png','image/webp'):abort(400,description='unsupported_image')
            try:raw=base64.b64decode(content,validate=True)
            except (ValueError,binascii.Error):abort(400,description='invalid_image')
            valid=(mime=='image/jpeg' and raw.startswith(b'\xff\xd8\xff') and raw.endswith(b'\xff\xd9')) or (mime=='image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (mime=='image/webp' and raw.startswith(b'RIFF') and raw[8:12]==b'WEBP')
            if not valid or not 32<=len(raw)<=2000000:abort(400,description='invalid_image_or_size')
            digest=hashlib.sha256(raw).hexdigest()
            with self.db() as c:
                existing=c.execute('SELECT id FROM shop_media WHERE sha256=?',(digest,)).fetchone()
                asset_id=existing[0] if existing else secrets.token_hex(16)
                if not existing:c.execute('INSERT INTO shop_media(id,filename,mime_type,content_base64,sha256,size_bytes,created_at) VALUES(?,?,?,?,?,?,?)',(asset_id,name,mime,content,digest,len(raw),self.now()))
                a.audit(c,'upload','media',asset_id,{'size_bytes':len(raw),'sha256':digest})
            return jsonify(id=asset_id,url='/media/'+asset_id),201
        route('/api/admin/store/media','store_media_upload',upload_media,('POST',),permission='catalog.write')

        def media_list():
            with self.db() as c:items=[{**dict(r),'url':'/media/'+r['id']} for r in c.execute('SELECT id,filename,mime_type,size_bytes,created_at FROM shop_media ORDER BY created_at DESC LIMIT 200')]
            seen=set()
            for product in self.a.CATALOG_PRODUCTS:
                if product['image'].endswith('.svg') or product['image'] in seen:continue
                seen.add(product['image']);items.append({'id':product['id'],'filename':product['title'],'url':'/static/images/'+product['image'],'kind':'catalog'})
            manifest=Path(self.a.BASE_DIR/'docs/research/store-assets-2026-11-11.json')
            if manifest.exists():
                for asset in json.loads(manifest.read_text())['downloads']:
                    filename=asset.get('file')
                    if asset.get('status')=='downloaded' and filename and (self.a.BASE_DIR/filename).is_file():
                        items.append({'id':asset['sha256'],'filename':asset.get('description') or 'Фото компании','url':'/'+filename,'kind':'company_gallery'})
            return jsonify(items)
        route('/api/admin/store/media','store_media_list',media_list,permission='catalog.read')

        @app.get('/account')
        def customer_account_page():return render_template('account.html')

        def catalog():
            with self.db() as c:return jsonify(products=self.catalog(c),settings=self.settings(c))
        route('/api/store/catalog','store_catalog',catalog)

        def promotions():
            with self.db() as c:
                rows=[dict(r) for r in c.execute('SELECT * FROM promotions WHERE active=1 ORDER BY code')]
                return jsonify([r for r in rows if self.a.eligible_promotion(c,r['code'],max(r['min_order'],1)) and not r['code'].startswith('RK-')])
        route('/api/store/promotions','store_promotions',promotions)


        def profile():
            guest,authenticated=self.identity()
            with self.db() as c:
                p=self.ensure_profile(c,guest);v=dict(a.get_visitor(c,guest));details=self.decrypt(p['ciphertext'])
                orders=self.private_orders(c,guest);ledger=[dict(r) for r in c.execute('SELECT delta,reason,created_at FROM shop_bonus_ledger WHERE guest_id=? ORDER BY created_at DESC LIMIT 100',(guest,))]
                prizes=[dict(r) for r in c.execute('SELECT prize_title,redemption_code,status,created_at FROM spins WHERE guest_id=? ORDER BY created_at DESC LIMIT 50',(guest,))]
                notices=[dict(r) for r in c.execute("SELECT * FROM shop_notifications WHERE audience='customer' AND guest_id=? ORDER BY created_at DESC LIMIT 50",(guest,))]
                return jsonify(guest_id=guest,authenticated=authenticated,csrf_token=a.csrf_token(),profile=details,favorites=json.loads(p['favorites_json']),balance=self.bonus_balance(c,guest),tickets=v['tickets'],orders=orders,ledger=ledger,prizes=prizes,notifications=notices,settings=self.settings(c))
        route('/api/store/profile','store_profile',profile)

        def save_profile():
            guest,authenticated=self.identity();data=request.get_json()
            with self.db() as c:
                old=self.ensure_profile(c,guest);value=self.decrypt(old['ciphertext'])
                if authenticated and 'email' in data and data['email'].strip().lower()!=value.get('email','').lower():abort(409,description='email_change_requires_reauthentication')
                for key,limit in [('name',80),('phone',32),('address',500),('email',254)]:
                    if key in data:
                        if not isinstance(data[key],str) or len(data[key])>limit:abort(400)
                        value[key]=data[key].strip()
                favorites=data.get('favorites',json.loads(old['favorites_json']))
                if not isinstance(favorites,list) or len(favorites)>100 or any(not isinstance(v,str) for v in favorites):abort(400)
                c.execute('UPDATE shop_profiles SET ciphertext=?,favorites_json=?,updated_at=? WHERE guest_id=?',
                          (self.encrypt(value),json.dumps(list(dict.fromkeys(favorites))),self.now(),guest))
            return jsonify(status='saved')
        route('/api/store/profile','store_profile_save',save_profile,('PUT',))

        def register_account():
            if a.rate_limited('customer_registration',5):abort(429)
            guest,authenticated=self.identity();data=request.get_json();email=str(data.get('email','')).strip().lower();password=data.get('password','')
            if authenticated:abort(409,description='already_authenticated')
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(email)>254 or not isinstance(password,str) or not 12<=len(password)<=256:abort(400,description='invalid_registration')
            digest=hmac.new(str(app.secret_key).encode(),email.encode(),hashlib.sha256).hexdigest()
            with self.db() as c:
                if c.execute('SELECT 1 FROM shop_accounts WHERE email_digest=? OR guest_id=?',(digest,guest)).fetchone():abort(409,description='account_exists')
                p=self.ensure_profile(c,guest);details=self.decrypt(p['ciphertext']);details['email']=email
                account_id=secrets.token_hex(16)
                c.execute('INSERT INTO shop_accounts(id,guest_id,email_digest,password_hash,created_at) VALUES(?,?,?,?,?)',(account_id,guest,digest,generate_password_hash(password),self.now()))
                c.execute('UPDATE shop_profiles SET ciphertext=?,updated_at=? WHERE guest_id=?',(self.encrypt(details),self.now(),guest))
                self.create_session(c,account_id)
            return jsonify(status='registered'),201
        route('/api/store/auth/register','customer_register',register_account,('POST',))

        def login():
            if a.rate_limited('customer_login',10,900):abort(429)
            d=request.get_json();email=str(d.get('email','')).strip().lower();password=d.get('password','')
            if not isinstance(password,str) or len(password)>256:abort(400)
            digest=hmac.new(str(app.secret_key).encode(),email.encode(),hashlib.sha256).hexdigest()
            with self.db() as c:
                account=c.execute('SELECT * FROM shop_accounts WHERE email_digest=?',(digest,)).fetchone()
                if not account or not check_password_hash(account['password_hash'],password):abort(401,description='invalid_credentials')
                blocked=c.execute('SELECT blocked FROM shop_profiles WHERE guest_id=?',(account['guest_id'],)).fetchone()
                if blocked and blocked[0]:abort(403,description='customer_blocked')
                self.create_session(c,account['id']);session['guest_id']=account['guest_id']
            return jsonify(status='authenticated')
        route('/api/store/auth/login','customer_login',login,('POST',))

        def logout():
            token=session.pop('customer_token','')
            with self.db() as c:c.execute('DELETE FROM shop_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
            session.pop('guest_id',None);session.pop('max_guest_id',None)
            return jsonify(status='signed_out')
        route('/api/store/auth/logout','customer_logout',logout,('POST',))

        def quote():
            guest,_=self.identity()
            with self.db() as c:return jsonify(self.quote(c,request.get_json(),guest))
        route('/api/store/quote','store_quote',quote,('POST',))

        def order():
            if a.rate_limited('store_orders',10):abort(429)
            guest,_=self.identity();data=request.get_json()
            name=str(data.get('name','')).strip();phone=str(data.get('phone','')).strip();address=str(data.get('address','')).strip();comment=str(data.get('comment','')).strip()
            if not 2<=len(name)<=80 or not re.fullmatch(r'[+0-9 ()-]{6,32}',phone) or len(address)>500 or len(comment)>1000 or data.get('consent') is not True:abort(400,description='invalid_checkout')
            if data.get('delivery_mode')=='delivery' and len(address)<8:abort(400,description='address_required')
            payment=data.get('payment_method','on_receipt')
            if payment not in ('on_receipt','cash','card_on_receipt'):abort(400,description='unsupported_payment_method')
            with self.db() as c:
                receipt,replay=request_receipt(c,guest,'store_order',data)
                if replay:return jsonify(replay[0]),replay[1]
                p=self.ensure_profile(c,guest)
                if p['blocked']:abort(403,description='customer_blocked')
                q=self.quote(c,data,guest)
                if not q['rules']['accepting_orders']:abort(409,description='store_temporarily_closed')
                if data.get('promo_code') and not q['promo_valid']:abort(409,description='promotion_not_available')
                oid='RK-'+secrets.token_hex(5).upper();now=self.now()
                if q['reward_spin_id'] is not None:
                    if c.execute("UPDATE spins SET status='reserved' WHERE id=? AND guest_id=? AND status='unclaimed'",(q['reward_spin_id'],guest)).rowcount!=1:abort(409,description='reward_already_used')
                reserved={}
                for line in q['items']:
                    if line['reserved_milli']:reserved[line['id']]=reserved.get(line['id'],0)+line['reserved_milli']
                for pid,amount in reserved.items():
                    item={'id':pid,'quantity_milli':amount,'reserved_milli':amount}
                    if item['reserved_milli']:
                        changed=c.execute('UPDATE shop_inventory SET quantity_milli=quantity_milli-?,updated_at=? WHERE product_id=? AND quantity_milli>=?',(item['quantity_milli'],now,item['id'],item['quantity_milli']))
                        if changed.rowcount!=1:abort(409,description='insufficient_stock')
                        c.execute('INSERT INTO shop_stock_ledger(id,product_id,delta_milli,reason,reference,actor,created_at) VALUES(?,?,?,?,?,?,?)',
                                  (secrets.token_hex(16),item['id'],-item['quantity_milli'],'Резерв заказа','reserve:'+oid,'customer',now))
                c.execute('INSERT INTO orders(id,created_at,customer_label,contact_label,delivery_mode,address_label,items_json,subtotal_rub,discount_rub,delivery_rub,total_rub,promo_code,status,is_demo,guest_id,source_channel) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (oid,now,'Покупатель','ЗАШИФРОВАНО',data.get('delivery_mode','pickup'),'ЗАШИФРОВАНО',json.dumps(q['items'],ensure_ascii=False),q['subtotal_rub'],q['discount_rub']+q['bonus_spent'],q['delivery_rub'],q['total_rub'],q['promo_code'],'received',0,guest,'store'))
                private={'name':name,'phone':phone,'address':address,'comment':comment}
                c.execute('INSERT INTO shop_order_details(order_id,ciphertext,payment_method,bonus_spent,rules_json) VALUES(?,?,?,?,?)',(oid,self.encrypt(private),payment,q['bonus_spent'],json.dumps({'bonus_earned':q['bonus_earned'],'cashback_percent':q['rules']['cashback_percent'],'reward_spin_id':q['reward_spin_id']})))
                if q['bonus_spent']:self.bonus(c,guest,-q['bonus_spent'],'Списание в заказе '+oid,'spend:'+oid)
                if q['promo_code']:
                    changed=c.execute('UPDATE promotions SET uses=uses+1 WHERE code=? AND active=1 AND (max_uses=0 OR uses<max_uses)',(q['promo_code'],))
                    if changed.rowcount!=1:abort(409,description='promotion_exhausted')
                c.execute('INSERT INTO order_status_history(id,order_id,previous_status,new_status,actor,created_at) VALUES(?,?,?,?,?,?)',(secrets.token_hex(16),oid,'','received','customer',now))
                self.notice(c,guest,oid,'customer','new_order','Заказ '+oid,'Получен. Ожидает подтверждения оператором.')
                self.notice(c,'',oid,'staff','new_order','Новый заказ '+oid,str(q['total_rub'])+' ₽ · '+str(len(q['items']))+' позиций')
                for provider in q['rules']['notification_channels']:
                    c.execute('INSERT INTO shop_outbox(id,provider,body,created_at) VALUES(?,?,?,?)',('order:'+oid+':'+provider,provider,'РАКОВАРЪ · новый заказ '+oid+'\n'+str(q['total_rub'])+' ₽ · '+str(len(q['items']))+' позиций. Подробности в панели магазина.',now))
                if data.get('save_profile'):
                    details=self.decrypt(p['ciphertext']);details.update(name=name,phone=phone,address=address)
                    c.execute('UPDATE shop_profiles SET ciphertext=?,updated_at=? WHERE guest_id=?',(self.encrypt(details),now,guest))
                result={'status':'order_created','order_id':oid,'total_rub':q['total_rub'],'bonus_earned':q['bonus_earned'],'message':'Заказ получен. Его состав и время получения подтвердит оператор. Оплата при получении.'}
                save_receipt(c,guest,'store_order',receipt,result,201,now)
                a.event(c,'order_created',guest,{'order_id':oid,'total_rub':q['total_rub']})
            self.flush_notifications()
            return jsonify(result),201
        route('/api/store/orders','store_order_create',order,('POST',))

        def store_settings():
            with self.db() as c:return jsonify(self.settings(c))
        route('/api/admin/store/settings','store_settings_get',store_settings,permission='settings.read')

        def update_settings():
            d=request.get_json()
            if set(d)-set(DEFAULTS):abort(400,description='unknown_store_setting')
            with self.db() as c:
                config=self.settings(c)
                for key,value in d.items():
                    if key in ('accepting_orders','loyalty_enabled','builder_enabled','contests_visible'):
                        if not isinstance(value,bool):abort(400)
                    elif key=='notification_channels':
                        if not isinstance(value,list) or len(value)>2 or any(x not in ('max','telegram') for x in value):abort(400)
                    elif key=='gift_mappings':
                        if not isinstance(value,dict) or len(value)>30 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>100 or len(v)>100 for k,v in value.items()):abort(400)
                        for product_id in value.values():
                            if product_id and not c.execute('SELECT 1 FROM products WHERE id=? AND active=1',(product_id,)).fetchone():abort(400,description='gift_product_not_found')
                    elif key=='order_comment':
                        if not isinstance(value,str) or len(value)>500:abort(400)
                    else:
                        if not isinstance(value,int) or isinstance(value,bool) or value<0 or value>100000:abort(400)
                        if key in ('cashback_percent','bonus_spend_percent') and value>50:abort(400)
                        if key=='welcome_bonus' and value!=0:abort(400,description='verified_identity_required_for_welcome_bonus')
                        if key=='catalog_page_size' and not 6<=value<=100:abort(400)
                    config[key]=value
                c.execute("INSERT INTO site_settings(setting_key,setting_value,updated_at) VALUES('store_operations',?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=excluded.updated_at",(json.dumps(config),self.now()))
                a.audit(c,'configure','store','operations',{'keys':list(d)})
            return jsonify(status='saved')
        route('/api/admin/store/settings','store_settings_update',update_settings,('PUT',),permission='settings.write')

        def inventory():
            with self.db() as c:
                result=[]
                for p in c.execute('SELECT * FROM products ORDER BY category,title').fetchall():
                    inv=dict(self.inventory(c,p));inv.update(title=p['title'],unit=p['unit'],image=p['image'],image_url=p['image_url'],price=p['price'],active=p['active']);result.append(inv)
                return jsonify(result)
        route('/api/admin/store/inventory','store_inventory_get',inventory,permission='catalog.read')

        def update_inventory(product_id):
            d=request.get_json();reason=str(d.get('reason','')).strip()
            if not 3<=len(reason)<=200:abort(400,description='inventory_reason_required')
            with self.db() as c:
                p=c.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone()
                if not p:abort(404)
                old=self.inventory(c,p)
                try:
                    raw_quantity=Decimal(str(d.get('quantity')))*1000
                    qty=int(raw_quantity)
                    if raw_quantity!=qty:raise ValueError()
                except (InvalidOperation,ValueError,OverflowError):abort(400)
                if not 0<=qty<=100000000 or not isinstance(d.get('tracked'),bool):abort(400)
                expected=d.get('expected_quantity_milli')
                if expected!=old['quantity_milli']:abort(409,description='inventory_changed_reload')
                step=d.get('step_milli',old['step_milli']);threshold=d.get('threshold_milli',old['threshold_milli'])
                if step not in (100,250,500,1000) or not isinstance(threshold,int) or not 0<=threshold<=100000000:abort(400)
                c.execute('UPDATE shop_inventory SET quantity_milli=?,tracked=?,step_milli=?,threshold_milli=?,updated_at=? WHERE product_id=?',(qty,int(d['tracked']),step,threshold,self.now(),product_id))
                ref='adjust:'+secrets.token_hex(16)
                c.execute('INSERT INTO shop_stock_ledger(id,product_id,delta_milli,reason,reference,actor,created_at) VALUES(?,?,?,?,?,?,?)',(secrets.token_hex(16),product_id,qty-old['quantity_milli'],reason,ref,a.staff_access.actor(),self.now()))
                a.audit(c,'adjust','inventory',product_id,{'delta_milli':qty-old['quantity_milli'],'tracked':d['tracked'],'reason':reason})
            return jsonify(status='saved')
        route('/api/admin/store/inventory/<product_id>','store_inventory_update',update_inventory,('PUT',),permission='inventory.write')

        def inventory_history(product_id):
            with self.db() as c:return jsonify([dict(r) for r in c.execute('SELECT * FROM shop_stock_ledger WHERE product_id=? ORDER BY created_at DESC LIMIT 100',(product_id,))])
        route('/api/admin/store/inventory/<product_id>/history','store_inventory_history',inventory_history,permission='catalog.read')

        def customers():
            with self.db() as c:
                result=[]
                for p in c.execute('SELECT p.*,v.points,v.tickets FROM shop_profiles p JOIN visitors v ON v.guest_id=p.guest_id ORDER BY p.updated_at DESC LIMIT 300').fetchall():
                    item=dict(p);item.update(self.decrypt(item.pop('ciphertext')))
                    item['points']=self.bonus_balance(c,p['guest_id'])
                    item['orders']=c.execute('SELECT COUNT(*) FROM orders WHERE guest_id=?',(p['guest_id'],)).fetchone()[0];result.append(item)
                return jsonify(result)
        route('/api/admin/store/customers','store_customers',customers,permission='customers.read')

        def update_customer(guest_id):
            d=request.get_json()
            with self.db() as c:
                p=c.execute('SELECT * FROM shop_profiles WHERE guest_id=?',(guest_id,)).fetchone()
                if not p:abort(404)
                if 'blocked' in d:
                    if not isinstance(d['blocked'],bool):abort(400)
                    c.execute('UPDATE shop_profiles SET blocked=?,updated_at=? WHERE guest_id=?',(int(d['blocked']),self.now(),guest_id))
                    if d['blocked']:c.execute('DELETE FROM shop_sessions WHERE account_id IN (SELECT id FROM shop_accounts WHERE guest_id=?)',(guest_id,))
                if 'bonus_delta' in d:
                    delta=d['bonus_delta'];reason=str(d.get('reason','')).strip();key=request.headers.get('Idempotency-Key','')
                    if not isinstance(delta,int) or isinstance(delta,bool) or not -10000<=delta<=10000 or len(reason)<3 or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',key):abort(400)
                    previous=c.execute('SELECT guest_id,delta,reason FROM shop_bonus_ledger WHERE reference=?',('manual:'+key,)).fetchone()
                    if previous and (previous['guest_id']!=guest_id or previous['delta']!=delta or previous['reason']!=reason):abort(409,description='idempotency_payload_conflict')
                    if not self.bonus(c,guest_id,delta,reason,'manual:'+key):return jsonify(status='replayed')
                    a.audit(c,'adjust_bonus','customer',guest_id,{'delta':delta,'reason':reason})
                if any(k in d for k in ('name','phone','address')):
                    value=self.decrypt(p['ciphertext'])
                    for key,limit in [('name',80),('phone',32),('address',500)]:
                        if key in d:
                            if not isinstance(d[key],str) or len(d[key])>limit:abort(400)
                            value[key]=d[key].strip()
                    c.execute('UPDATE shop_profiles SET ciphertext=?,updated_at=? WHERE guest_id=?',(self.encrypt(value),self.now(),guest_id))
                    a.audit(c,'update_profile','customer',guest_id,{'keys':[k for k in d if k in ('name','phone','address')]})
            return jsonify(status='saved')
        route('/api/admin/store/customers/<guest_id>','store_customer_update',update_customer,('PATCH',),permission='customers.write')

        def admin_orders():
            with self.db() as c:return jsonify(self.private_orders(c,staff=True))
        route('/api/admin/store/orders','store_admin_orders',admin_orders,permission='orders.read')

        def notifications():
            with self.db() as c:
                return jsonify(notifications=[dict(r) for r in c.execute("SELECT * FROM shop_notifications WHERE audience='staff' ORDER BY created_at DESC LIMIT 100")],outbox=[dict(r) for r in c.execute('SELECT * FROM shop_outbox ORDER BY created_at DESC LIMIT 100')])
        route('/api/admin/store/notifications','store_notifications',notifications,permission='orders.read')

        def read_notifications():
            with self.db() as c:c.execute("UPDATE shop_notifications SET read_at=? WHERE audience='staff' AND read_at=''",(self.now(),))
            return jsonify(status='read')
        route('/api/admin/store/notifications/read','store_notifications_read',read_notifications,('POST',),permission='orders.read')

        route('/api/admin/store/notifications/dispatch','store_notifications_dispatch',lambda:jsonify(self.flush_notifications()),('POST',),permission='integrations.manage')

    def create_session(self,c,account_id):
        old=session.get('customer_token','')
        if old:c.execute('DELETE FROM shop_sessions WHERE token_hash=?',(hashlib.sha256(old.encode()).hexdigest(),))
        token=secrets.token_urlsafe(32)
        c.execute('INSERT INTO shop_sessions(token_hash,account_id,expires_at) VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),account_id,int(time.time())+43200))
        session['customer_token']=token
        session.permanent=True
