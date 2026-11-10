"""Provider storage, permissions and ambiguous external delivery boundaries."""
import json
import pytest
import connections as provider_module
from test_app import app_module, client, admin_login

@pytest.fixture()
def setup(client,app_module,monkeypatch):
    monkeypatch.setenv('INTEGRATION_ENCRYPTION_KEY','test-only-integration-master-32-characters')
    csrf=admin_login(client)
    return client,app_module,{'X-CSRF-Token':csrf}

def save_max(client,headers):
    return client.put('/api/admin/connections/max',headers=headers,json={'password':'test-admin-password','values':{'bot_token':'synthetic-private-provider-token','chat_id':'-12345'},'enabled':True})

def test_credentials_encrypted_redacted_and_reauthentication_required(setup):
    client,app,headers=setup
    bad=client.put('/api/admin/connections/max',headers=headers,json={'password':'bad','values':{'bot_token':'do-not-store'}})
    assert bad.status_code==401
    assert save_max(client,headers).status_code==200
    body=client.get('/api/admin/connections').json
    assert 'synthetic-private-provider-token' not in json.dumps(body)
    max_config=next(p for p in body if p['id']=='max')
    assert max_config['configured'] and not max_config['verified']
    with app.connect_db() as c:
        raw=c.execute("SELECT ciphertext FROM provider_connections WHERE provider='max'").fetchone()[0]
        assert 'synthetic-private-provider-token' not in raw and 'chat_id' not in raw
        assert 'synthetic-private-provider-token' not in json.dumps([dict(r) for r in c.execute('SELECT * FROM audit_log')])
    assert app.connections.config('max')['bot_token']=='synthetic-private-provider-token'
    assert client.put('/api/admin/connections/max',json={'password':'test-admin-password'}).status_code==400

def test_read_only_check_does_not_send_and_save_invalidates_check(setup,monkeypatch):
    client,app,headers=setup;save_max(client,headers);calls=[]
    def transport(provider,config,action,*args):
        calls.append(action);return {'identity':'Rakovar test bot'}
    monkeypatch.setattr(provider_module,'provider_request',transport)
    assert client.post('/api/admin/connections/max/check',headers=headers,json={}).status_code==200
    assert calls==['check']
    assert next(p for p in client.get('/api/admin/connections').json if p['id']=='max')['verified']
    assert save_max(client,headers).status_code==200
    assert not next(p for p in client.get('/api/admin/connections').json if p['id']=='max')['verified']

def test_confirmed_delivery_replayed_and_payload_conflict_prevented(setup,monkeypatch):
    client,app,headers=setup;save_max(client,headers);calls=[]
    def transport(*args):calls.append(args);return {'remote_id':'server-confirmed-message-1'}
    monkeypatch.setattr(provider_module,'provider_request',transport)
    request_headers={**headers,'Idempotency-Key':'same-delivery-request-123456'}
    body={'password':'test-admin-password','confirm_send':True,'text':'Сообщение'}
    first=client.post('/api/admin/connections/max/test',headers=request_headers,json=body)
    assert first.status_code==200 and first.json['remote_id']=='server-confirmed-message-1'
    assert client.post('/api/admin/connections/max/test',headers=request_headers,json=body).json['replayed']
    body['text']='Другой текст'
    assert client.post('/api/admin/connections/max/test',headers=request_headers,json=body).status_code==409
    assert len(calls)==1


def test_uncertain_delivery_never_retries_automatically(setup,monkeypatch):
    client,app,headers=setup;save_max(client,headers);calls=[]
    def transport(*args):calls.append(args);raise provider_module.ConnectionError('provider_response_unknown',502)
    monkeypatch.setattr(provider_module,'provider_request',transport)
    with pytest.raises(provider_module.ConnectionError,match='provider_response_unknown'):app.connections.deliver('max','Сообщение','uncertain-delivery')
    with pytest.raises(provider_module.ConnectionError,match='delivery_requires_manual_review'):app.connections.deliver('max','Сообщение','uncertain-delivery')
    assert len(calls)==1

def test_webhook_authentication_and_replay_metadata(setup):
    client,app,headers=setup
    assert client.put('/api/admin/connections/telegram',headers=headers,json={'password':'test-admin-password','values':{'bot_token':'synthetic-telegram-token','chat_id':'-999'}}).status_code==200
    secret=app.connections.config('telegram')['webhook_secret'];event={'update_id':123,'message':{'text':'private incoming text'}}
    assert client.post('/api/webhooks/telegram',json=event).status_code==403
    for _ in range(2):assert client.post('/api/webhooks/telegram',headers={'X-Telegram-Bot-Api-Secret-Token':secret},json=event).status_code==200
    with app.connect_db() as c:
        events=[dict(r) for r in c.execute('SELECT * FROM provider_events')]
        assert len(events)==1 and 'private incoming text' not in json.dumps(events)

def test_publisher_requires_approval_and_confirms_each_channel(setup,monkeypatch):
    client,app,headers=setup;save_max(client,headers)
    monkeypatch.setattr(provider_module,'provider_request',lambda *args:{'remote_id':'real-adapter-response-id'})
    post=client.post('/api/admin/content',headers=headers,json={'title':'Проверка','body':'Состав нового сета','channels':['max'],'status':'approved'})
    assert post.status_code==201
    url=f"/api/admin/content/{post.json['id']}/publish"
    assert client.post(url,headers=headers,json={}).json['status']=='published'
    assert client.post(url,headers=headers,json={}).json['results']['max']['replayed']

def test_content_editor_cannot_read_or_change_connections(setup):
    client,app,headers=setup
    created=client.post('/api/admin/staff',headers=headers,json={'username':'limited_editor','password':'synthetic-staff-password','role':'content_editor'})
    assert created.status_code==201
    client.post('/admin/logout',data={'csrf_token':headers['X-CSRF-Token']})
    client.get('/admin/login')
    with client.session_transaction() as session:csrf=session['admin_csrf']
    assert client.post('/admin/login',data={'username':'limited_editor','password':'synthetic-staff-password','csrf_token':csrf}).status_code==302
    assert client.get('/api/admin/connections').status_code==403

@pytest.mark.parametrize('provider,action,payload,remote_id',[
    ('vk','send',{'response':{'post_id':7}},'7'),
    ('max','send',{'message':{'body':{'mid':'mid-123'}}},'mid-123'),
    ('telegram','send',{'ok':True,'result':{'message_id':9}},'9'),
])
def test_official_transport_contracts(provider,action,payload,remote_id,monkeypatch):
    calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps(payload).encode()
    class Opener:
        def open(self,request,timeout):calls.append(request);return Response()
    monkeypatch.setattr(provider_module,'build_opener',lambda *args:Opener())
    config={'group_id':'123','community_token':'synthetic-community-token','user_token':'synthetic-wall-token','bot_token':'123:synthetic-bot-token','chat_id':'-456'}
    assert provider_module.provider_request(provider,config,action,'hello','stable-id')['remote_id']==remote_id
    request=calls[0]
    assert request.method=='POST'
    if provider=='vk':
        assert request.full_url=='https://api.vk.com/method/wall.post'
        assert b'owner_id=-123' in request.data and b'guid=stable-id' in request.data
        assert 'synthetic-wall-token' not in request.full_url
    elif provider=='max':
        assert request.full_url=='https://platform-api2.max.ru/messages?chat_id=-456'
        assert request.get_header('Authorization')==config['bot_token']
        assert json.loads(request.data)=={'text':'hello'}
    else:
        assert request.full_url.endswith('/sendMessage')
        assert json.loads(request.data)=={'chat_id':'-456','text':'hello'}

def test_malformed_provider_response_is_not_success(monkeypatch):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return b'{"ok":true,"result":[]}'
    class Opener:
        def open(self,*args,**kwargs):return Response()
    monkeypatch.setattr(provider_module,'build_opener',lambda *args:Opener())
    with pytest.raises(provider_module.ConnectionError):
        provider_module.provider_request('telegram',{'bot_token':'synthetic','chat_id':'-1'},'send','hello','id')

def test_saved_max_token_used_by_bot_replies(setup,monkeypatch):
    client,app,headers=setup;save_max(client,headers)
    import sys
    sys.modules.pop('max_bot',None)
    import max_bot
    calls=[]
    monkeypatch.setattr(max_bot,'send_message',lambda **kwargs:calls.append(kwargs) or {})
    max_bot._send_user(123,'hello')
    assert calls[0]['token']=='synthetic-private-provider-token'
