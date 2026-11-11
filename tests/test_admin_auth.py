"""Keep main's duplicate-tab/CSRF regression fixes with individual staff sessions."""
from test_app import app_module, client


def test_repeated_gets_do_not_invalidate_admin_login_form(client):
    assert client.get('/admin/login').status_code == 200
    with client.session_transaction() as session:
        csrf = session['admin_csrf']
    assert client.get('/admin/login').status_code == 200
    with client.session_transaction() as session:
        assert session['admin_csrf'] == csrf
    response = client.post('/admin/login', data={'username':'owner','password':'test-admin-password','csrf_token':csrf})
    assert response.status_code == 302
    assert client.get('/api/admin/security/me').status_code == 200


def test_missing_csrf_returns_recoverable_html_form(client):
    response = client.post('/admin/login', data={'password':'test-admin-password'})
    assert response.status_code == 400
    assert response.content_type.startswith('text/html')
    assert b'name="csrf_token"' in response.data
    with client.session_transaction() as session:
        csrf = session['admin_csrf']
    response = client.post('/admin/login', data={'password':'test-admin-password','csrf_token':csrf})
    assert response.status_code == 302


def test_wrong_password_rejected(client):
    client.get('/admin/login')
    with client.session_transaction() as session:
        csrf = session['admin_csrf']
    assert client.post('/admin/login', data={'password':'incorrect','csrf_token':csrf}).status_code == 401
    assert client.get('/api/admin/security/me').status_code == 401
