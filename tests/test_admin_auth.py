"""Regression checks for demo administrator login and CSRF handling."""

import importlib
import pytest
from werkzeug.security import generate_password_hash


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-only-session-key-not-used-in-render")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("DEMO_MODE", "true")

    # The checked-in archive contains the HTML templates used by Render.
    prepare_render = importlib.import_module("prepare_render")
    assert prepare_render.main() == 0
    rakovar = importlib.import_module("app")
    monkeypatch.setattr(rakovar, "ADMIN_PASSWORD_HASH", generate_password_hash("test-only-password"))
    rakovar.app.config.update(TESTING=True, SECRET_KEY="test-only-session-key-not-used-in-render",
                               SESSION_COOKIE_SECURE=False)
    with rakovar.app.test_client() as test_client:
        yield test_client


def test_repeated_gets_do_not_invalidate_admin_login_form(client):
    assert client.get("/admin/login").status_code == 200
    with client.session_transaction() as sess:
        csrf = sess["admin_csrf"]
    assert client.get("/admin/login").status_code == 200
    with client.session_transaction() as sess:
        assert sess["admin_csrf"] == csrf

    response = client.post("/admin/login", data={"csrf_token": csrf, "password": "test-only-password"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin")
    with client.session_transaction() as sess:
        assert sess.get("admin") is True


def test_missing_csrf_returns_recoverable_html_form(client):
    response = client.post("/admin/login", data={"password": "test-only-password"})
    assert response.status_code == 400
    assert response.content_type.startswith("text/html")
    assert b'name="csrf_token"' in response.data
    with client.session_transaction() as sess:
        csrf = sess["admin_csrf"]
    response = client.post("/admin/login", data={"csrf_token": csrf, "password": "test-only-password"})
    assert response.status_code == 302


def test_wrong_password_rejected(client):
    client.get("/admin/login")
    with client.session_transaction() as sess:
        csrf = sess["admin_csrf"]
    response = client.post("/admin/login", data={"csrf_token": csrf, "password": "incorrect"})
    assert response.status_code == 401
    with client.session_transaction() as sess:
        assert sess.get("admin") is not True
