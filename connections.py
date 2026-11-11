"""Encrypted, owner-managed provider connections and explicit outbound actions.

Fixed provider hosts, no redirects, no token-bearing error text. Saving/checking
never sends a message. Message/publishing calls are separate deliberate actions.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from cryptography.fernet import Fernet, InvalidToken
from flask import jsonify, request, abort
from staff_auth import StaffError
from max_client import _ssl_context

PROVIDERS = {
 'vk': {'title':'ВКонтакте','fields':{'group_id':False,'community_token':True,'user_token':True,'webhook_secret':True,'confirmation_code':True},'env':{'group_id':'VK_GROUP_ID','community_token':'VK_GROUP_TOKEN','user_token':'VK_USER_TOKEN'},'required':['group_id','community_token'],'help':'Ключ сообщества — для сообщений. Для публикаций на стене нужен отдельный пользовательский токен с правами wall.'},
 'max': {'title':'MAX','fields':{'bot_token':True,'chat_id':False,'bot_username':False,'webhook_secret':True},'env':{'bot_token':'MAX_BOT_TOKEN','chat_id':'MAX_CHAT_ID','bot_username':'MAX_BOT_USERNAME'},'required':['bot_token'],'help':'Создайте бота, добавьте его в нужный чат или канал и укажите chat_id. Проверка ключа не заменяет проверку прав канала.'},
 'telegram': {'title':'Telegram','fields':{'bot_token':True,'chat_id':False,'webhook_secret':True},'env':{'bot_token':'TELEGRAM_BOT_TOKEN','chat_id':'TELEGRAM_CHAT_ID'},'required':['bot_token'],'help':'Добавьте бота администратором в канал. Укажите chat_id или @имя_канала. Для личных уведомлений сначала откройте бота и нажмите /start.'},
}

class ConnectionError(ValueError):
 def __init__(self, code, status=400): self.code,self.status=code,status;super().__init__(code)

class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self, req, fp, code, msg, headers, newurl): return None

def provider_request(provider, config, action, text='', key=''):
 """Only documented, allowlisted provider operations; secrets never enter logs."""
 headers={'Accept':'application/json','User-Agent':'Rakovar/1.0'}
 body=None;method='GET'
 if provider=='vk':
  params={'v':'5.199','access_token':config.get('user_token') if action=='send' else config.get('community_token'),'group_id':config['group_id']}
  endpoint='groups.getById'
  if action=='send':
   if not config.get('user_token'): raise ConnectionError('vk_wall_user_token_required',409)
   endpoint='wall.post';params={'v':'5.199','access_token':config['user_token'],'owner_id':'-'+config['group_id'],'from_group':1,'message':text,'guid':key}
  url='https://api.vk.com/method/'+endpoint;body=urlencode(params).encode();method='POST';headers['Content-Type']='application/x-www-form-urlencoded'
 elif provider=='max':
  headers['Authorization']=config['bot_token'];url='https://platform-api2.max.ru/me'
  if action=='send':url='https://platform-api2.max.ru/messages?'+urlencode({'chat_id':config['chat_id']});body=json.dumps({'text':text}).encode();method='POST'
  if action=='subscribe':url='https://platform-api2.max.ru/subscriptions';body=json.dumps({'url':config['webhook_url'],'update_types':['bot_started','message_created'],'secret':config['webhook_secret']}).encode();method='POST'
 else:
  token=config['bot_token'];url='https://api.telegram.org/bot'+token+'/getMe'
  if action=='send':url='https://api.telegram.org/bot'+token+'/sendMessage';body=json.dumps({'chat_id':config['chat_id'],'text':text}).encode();method='POST'
  if action=='subscribe':url='https://api.telegram.org/bot'+token+'/setWebhook';body=json.dumps({'url':config['webhook_url'],'secret_token':config['webhook_secret'],'allowed_updates':['message','channel_post']}).encode();method='POST'
 if body is not None and 'Content-Type' not in headers:headers['Content-Type']='application/json'
 try:
  with build_opener(NoRedirect(),HTTPSHandler(context=_ssl_context() if provider == 'max' else None)).open(Request(url,data=body,method=method,headers=headers),timeout=15) as response:
   raw=response.read(1000001)
   if len(raw)>1000000:raise ConnectionError('provider_response_too_large',502)
   result=json.loads(raw)
 except HTTPError as exc:raise ConnectionError('provider_auth_failed' if exc.code in (401,403) else 'provider_http_error',502) from None
 except (URLError,TimeoutError,OSError,ValueError):raise ConnectionError('provider_response_unknown',502) from None
 if not isinstance(result,dict) or result.get('error') or result.get('ok') is False:raise ConnectionError('provider_rejected_request',502)
 if action=='send':
  if any(not isinstance(result.get(k,{}),dict) for k in ('response','message','result')):raise ConnectionError('provider_response_unknown',502)
  if provider=='max' and not isinstance(result.get('message',{}).get('body',{}),dict):raise ConnectionError('provider_response_unknown',502)
  mid=result.get('response',{}).get('post_id') if provider=='vk' else result.get('message',{}).get('body',{}).get('mid') if provider=='max' else result.get('result',{}).get('message_id')
  if mid is None:raise ConnectionError('provider_response_unknown',502)
  return {'remote_id':str(mid)}
 if action=='check':
  if provider=='vk':
   response=result.get('response',{})
   if not isinstance(response,dict):raise ConnectionError('provider_response_unknown',502)
   groups=response.get('groups',[])
   if not isinstance(groups,list) or any(not isinstance(group,dict) for group in groups):raise ConnectionError('provider_response_unknown',502)
   if not groups or str(groups[0].get('id'))!=str(config['group_id']):raise ConnectionError('destination_mismatch',409)
   return {'identity':str(groups[0].get('name','Сообщество'))[:120]}
  account=result.get('result',{}) if provider=='telegram' else result
  if not isinstance(account,dict) or account.get('is_bot') is not True:raise ConnectionError('bot_identity_unconfirmed',409)
  return {'identity':str(account.get('username') or account.get('name') or account.get('first_name') or 'Бот')[:120]}
 return {'accepted':True}

class Connections:
 def __init__(self,app,connect_db,staff,csrf,audit):
  self.app,self.db,self.staff,self.csrf,self.audit=app,connect_db,staff,csrf,audit
 def cipher(self):
  master=os.environ.get('INTEGRATION_ENCRYPTION_KEY','')
  if not master and self.app.testing:master=str(self.app.secret_key)
  if len(master)<24:raise ConnectionError('encryption_key_required',503)
  return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('rakovar-connections-v1:'+master).encode()).digest()))
 def stored(self,provider):
  with self.db() as c:r=c.execute('SELECT * FROM provider_connections WHERE provider=?',(provider,)).fetchone()
  if not r:return {},None
  try:return json.loads(self.cipher().decrypt(r['ciphertext'].encode())),dict(r)
  except InvalidToken:raise ConnectionError('connection_key_mismatch',503) from None
 def config(self,provider):
  spec=PROVIDERS[provider];config={k:os.environ.get(env,'').strip() for k,env in spec['env'].items()}
  config.update(self.stored(provider)[0]);return config
 @staticmethod
 def digest(config):return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
 def list(self):
  result=[]
  try:self.cipher();storage=True
  except ConnectionError:storage=False
  for provider,spec in PROVIDERS.items():
   config=self.config(provider);_,record=self.stored(provider)
   present=all(config.get(k) for k in spec['required']) and config.get('enabled',True)
   checked=bool(record and record['verified_digest']==self.digest(config) and present)
   result.append({'id':provider,'title':spec['title'],'help':spec['help'],'configured':bool(present),'enabled':config.get('enabled',True),'verified':checked,'checked_at':record['checked_at'] if record else '', 'identity':record['identity'] if checked else '', 'storage_ready':storage,'fields':[{'key':k,'secret':secret,'configured':bool(config.get(k)),'value':None if secret else config.get(k,'')} for k,secret in spec['fields'].items()],'can_publish':bool(checked and config.get('chat_id' if provider!='vk' else 'user_token')),'webhook_url':os.environ.get('PUBLIC_BASE_URL','').rstrip('/')+('/api/max/webhook' if provider=='max' else '/api/webhooks/'+provider)})
  return result
 def save(self,provider,data,principal):
  self.staff._reauth(principal,data.get('password',''))
  if os.environ.get('RENDER') and not os.environ.get('DATABASE_URL'):raise ConnectionError('durable_storage_required',503)
  config=self.config(provider)
  values=data.get('values',{})
  if not isinstance(values,dict) or set(values)-set(PROVIDERS[provider]['fields']):raise ConnectionError('invalid_connection_fields')
  for k,v in values.items():
   if not isinstance(v,str) or len(v)>8192:raise ConnectionError('invalid_connection_value')
   if v.strip():config[k]=v.strip()
  cleared=data.get('clear_fields',[])
  if not isinstance(cleared,list) or any(not isinstance(k,str) for k in cleared):raise ConnectionError('invalid_connection_fields')
  for k in cleared:
   if k not in PROVIDERS[provider]['fields']:raise ConnectionError('invalid_connection_fields')
   config[k]=''
  if config.get('bot_username') and not re.fullmatch(r'[A-Za-z0-9_]{3,128}',config['bot_username']):raise ConnectionError('invalid_bot_username')
  if config.get('group_id') and not re.fullmatch(r'[1-9][0-9]{0,15}',config['group_id']):raise ConnectionError('invalid_group_id')
  if config.get('chat_id') and not re.fullmatch(r'-?[0-9]{1,20}|@[A-Za-z0-9_]{3,64}',config['chat_id']):raise ConnectionError('invalid_chat_id')
  if provider=='max' and config.get('chat_id') and not re.fullmatch(r'-?[0-9]{1,20}',config['chat_id']):raise ConnectionError('invalid_chat_id')
  if not config.get('webhook_secret'):config['webhook_secret']=secrets.token_urlsafe(32)
  if not re.fullmatch(r'[A-Za-z0-9_-]{5,256}',config['webhook_secret']):raise ConnectionError('invalid_webhook_secret')
  config['enabled']=data.get('enabled',True) is True
  ciphertext=self.cipher().encrypt(json.dumps(config).encode()).decode()
  with self.db() as c:
   c.execute("INSERT INTO provider_connections(provider,ciphertext) VALUES(?,?) ON CONFLICT(provider) DO UPDATE SET ciphertext=excluded.ciphertext,verified_digest='',checked_at='',identity=''",(provider,ciphertext))
   self.audit(c,'configure','connection',provider,{'enabled':config['enabled']})
 def check(self,provider):
  config=self.config(provider)
  if not config.get('enabled',True) or any(not config.get(k) for k in PROVIDERS[provider]['required']):raise ConnectionError('connection_not_configured',409)
  result=provider_request(provider,config,'check')
  with self.db() as c:
   c.execute('UPDATE provider_connections SET verified_digest=?,checked_at=?,identity=? WHERE provider=?',(self.digest(config),str(int(time.time())),result['identity'],provider))
   self.audit(c,'check','connection',provider,{'result':'token_valid'})
  return result
 def deliver(self,provider,text,delivery_id):
  config=self.config(provider)
  if not config.get('enabled',True) or any(not config.get(k) for k in PROVIDERS[provider]['required']):raise ConnectionError('connection_not_configured',409)
  if not config.get('chat_id' if provider!='vk' else 'user_token'):raise ConnectionError('destination_or_wall_token_required',409)
  if not isinstance(text,str) or not 1<=len(text)<=4000:raise ConnectionError('message_length_1_to_4000')
  digest=hashlib.sha256((self.digest(config)+'\0'+text).encode()).hexdigest()
  with self.db() as c:
   old=c.execute('SELECT * FROM provider_deliveries WHERE id=?',(delivery_id,)).fetchone()
   if old:
    if old['payload_digest']!=digest:raise ConnectionError('idempotency_payload_mismatch',409)
    if old['state']=='sent':return {'remote_id':old['remote_id'],'replayed':True}
    raise ConnectionError('delivery_requires_manual_review',409)
   c.execute('INSERT INTO provider_deliveries(id,provider,state,payload_digest,updated_at) VALUES(?,?,?,?,?)',(delivery_id,provider,'sending',digest,str(int(time.time()))))
  try:result=provider_request(provider,config,'send',text,delivery_id)
  except ConnectionError:
   with self.db() as c:c.execute("UPDATE provider_deliveries SET state='uncertain',updated_at=? WHERE id=?",(str(int(time.time())),delivery_id))
   raise
  with self.db() as c:
   c.execute("UPDATE provider_deliveries SET state='sent',remote_id=?,updated_at=? WHERE id=?",(result['remote_id'],str(int(time.time())),delivery_id))
   self.audit(c,'send','connection',provider,{'delivery_id':delivery_id,'remote_id':result['remote_id']})
  return result
 def register(self,admin_required):
  def secured(fn):
   def run(*args,**kwargs):
    try:
     if request.method!='GET':
      self.csrf()
      if not isinstance(request.get_json(silent=True),dict):raise ConnectionError('invalid_json')
     return fn(*args,**kwargs)
    except (ConnectionError,StaffError) as e:return jsonify(error=e.code),e.status
   run.__name__=fn.__name__;return admin_required(run)
  @secured
  def connections_list():return jsonify(self.list())
  @secured
  def connections_save(provider):
   if provider not in PROVIDERS:abort(404)
   self.save(provider,request.get_json() or {},self.staff.current_principal());return jsonify(status='saved')
  @secured
  def connections_check(provider):
   if provider not in PROVIDERS:abort(404)
   return jsonify(self.check(provider))
  @secured
  def connections_send(provider):
   if provider not in PROVIDERS:abort(404)
   data=request.get_json() or {};self.staff._reauth(self.staff.current_principal(),data.get('password',''))
   if data.get('confirm_send') is not True:raise ConnectionError('explicit_send_confirmation_required')
   key=request.headers.get('Idempotency-Key','')
   if not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}',key):raise ConnectionError('idempotency_key_required')
   return jsonify(self.deliver(provider,data.get('text',''),'test:'+provider+':'+hashlib.sha256(key.encode()).hexdigest()))
  @secured
  def connections_subscribe(provider):
   if provider not in ('max','telegram'):raise ConnectionError('vk_callback_manual_setup_required',409)
   data=request.get_json() or {};self.staff._reauth(self.staff.current_principal(),data.get('password',''))
   if data.get('confirm_subscribe') is not True:raise ConnectionError('explicit_webhook_confirmation_required')
   config=self.config(provider)
   if not config.get('enabled',True) or not config.get('bot_token'):raise ConnectionError('connection_not_configured',409)
   url=os.environ.get('PUBLIC_BASE_URL','').rstrip('/')
   if not url.startswith('https://') or not config.get('webhook_secret'):raise ConnectionError('public_https_url_required',409)
   return jsonify(provider_request(provider,{**config,'webhook_url':url+('/api/max/webhook' if provider=='max' else '/api/webhooks/'+provider)},'subscribe'))
  for path,name,fn,methods in [('/api/admin/connections','connections_list',connections_list,['GET']),('/api/admin/connections/<provider>','connections_save',connections_save,['PUT']),('/api/admin/connections/<provider>/check','connections_check',connections_check,['POST']),('/api/admin/connections/<provider>/test','connections_send',connections_send,['POST']),('/api/admin/connections/<provider>/webhook','connections_subscribe',connections_subscribe,['POST'])]:self.app.add_url_rule(path,name,fn,methods=methods)
  def incoming(provider):
   if provider not in PROVIDERS:abort(404)
   config=self.config(provider);data=request.get_json(silent=True)
   if not isinstance(data,dict):abort(400)
   if not config.get('enabled',True):abort(403)
   expected=config.get('webhook_secret','');supplied=data.get('secret','') if provider=='vk' else request.headers.get('X-Max-Bot-Api-Secret' if provider=='max' else 'X-Telegram-Bot-Api-Secret-Token','')
   if not expected or not hmac.compare_digest(str(expected),str(supplied)):abort(403)
   if provider=='vk' and str(data.get('group_id'))!=config.get('group_id'):abort(403)
   if provider=='vk' and data.get('type')=='confirmation':return config.get('confirmation_code',''),200
   event_id=hashlib.sha256((provider+json.dumps(data,sort_keys=True)).encode()).hexdigest()
   with self.db() as c:c.execute('INSERT INTO provider_events(id,provider,event_type,received_at) VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING',(event_id,provider,str(data.get('type') or data.get('update_type') or 'update')[:80],str(int(time.time()))))
   return ('ok',200) if provider=='vk' else jsonify(status='received')
  self.app.add_url_rule('/api/webhooks/<provider>','provider_incoming',incoming,methods=['POST'])
