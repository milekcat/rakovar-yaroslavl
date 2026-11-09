"""Staff security contracts, using real Flask requests and temporary SQLite."""
import json
import os

import pytest
from flask import Flask, abort, request, session
from werkzeug.security import generate_password_hash

from staff_auth import StaffAccess, StaffError, totp_code
from storage import connect_database


PASSWORD = "only-synthetic-pass-29"
OTHER_PASSWORD = "only-synthetic-pass-30"


@pytest.fixture
def security(tmp_path):
    db = tmp_path / "staff.sqlite3"
    def connect():
        return connect_database(db, database_url=None if os.environ.get("RAKOVAR_TEST_POSTGRES") == "1" else "")
    with connect() as c:
        c.execute("CREATE TABLE audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT,action TEXT,entity TEXT,entity_id TEXT,details_json TEXT,created_at TEXT)")
    app = Flask(__name__)
    app.config.update(SECRET_KEY="synthetic-test-cookie-key", TESTING=True)
    clock = [1800000000]
    access = StaffAccess(app, connect, bootstrap_hash=generate_password_hash(PASSWORD), now=lambda: clock[0], session_seconds=60)
    def csrf():
        if request.headers.get("X-CSRF-Token") != session.get("admin_csrf"):
            abort(400)
    access.register_routes(csrf)
    @app.post("/test-login")
    def login():
        data = request.get_json()
        try:
            p = access.login(data.get("username"), data.get("password"), data.get("otp", ""))
            return {"principal": p, "csrf": session["admin_csrf"]}
        except StaffError as exc:
            return {"error": exc.code}, exc.status
    @app.post("/test-logout")
    def logout():
        access.logout()
        return {"status": "logged_out"}
    return app, access, connect, clock


def login(client, username="owner", password=PASSWORD, otp=""):
    response = client.post("/test-login", json={"username": username, "password": password, "otp": otp})
    return response, {"X-CSRF-Token": (response.get_json() or {}).get("csrf", "")}


def create(client, headers, username="cataloger", role="catalog_manager"):
    return client.post("/api/admin/staff", json={"username": username, "password": OTHER_PASSWORD, "role": role}, headers=headers)


def test_unsigned_legacy_boolean_does_not_authenticate(security):
    app, access, _, _ = security
    with app.test_client() as client:
        with client.session_transaction() as cookie:
            cookie["admin"] = True
        assert client.get("/api/admin/security/me").status_code == 401
        with client.session_transaction() as cookie:
            assert "staff_token" not in cookie


def test_login_and_session_token_hashing_and_unknown_endpoint_denied(security):
    app, access, connect, _ = security
    with app.test_client() as client:
        response, _ = login(client)
        assert response.status_code == 200
        assert response.json["principal"]["role"] == "owner"
        assert client.get("/api/admin/security/me").status_code == 200
        with client.session_transaction() as cookie:
            token = cookie["staff_token"]
        with connect() as c:
            row = c.execute("SELECT * FROM staff_sessions").fetchone()
            assert row["token_hash"] != token
            assert row["token_hash"] == access._token_hash(token)
            assert token not in json.dumps(dict(row))
        with app.test_request_context():
            assert not access.allowed("unknown_future_admin_endpoint", response.json["principal"])
            assert access.allowed("admin_dashboard", response.json["principal"])


def test_account_create_csrf_and_scoped_role(security):
    app, access, _, _ = security
    with app.test_client() as owner:
        _, headers = login(owner)
        assert create(owner, {}).status_code == 400
        result = create(owner, headers)
        assert result.status_code == 201
        assert "password" not in result.json
        assert create(owner, headers).status_code == 409
    with app.test_client() as catalog:
        result, _ = login(catalog, "cataloger", OTHER_PASSWORD)
        assert result.status_code == 200
        p = result.json["principal"]
        assert access.allowed("admin_products", p)
        assert access.allowed("admin_product_update", p)
        assert not access.allowed("admin_orders", p)
        assert not access.allowed("admin_settings_update", p)
        assert catalog.get("/api/admin/staff").status_code == 403
        assert catalog.get("/api/admin/security/login-events").status_code == 403


def test_admin_cannot_create_or_reset_owners(security):
    app, _, _, _ = security
    with app.test_client() as owner:
        _, headers = login(owner)
        assert create(owner, headers, "admin-person", "admin").status_code == 201
        other_owner = create(owner, headers, "other-owner", "owner").json["id"]
    with app.test_client() as admin:
        _, headers = login(admin, "admin-person", OTHER_PASSWORD)
        assert create(admin, headers, "bad-owner", "owner").status_code == 403
        assert create(admin, headers, "bad-admin", "admin").status_code == 403
        assert admin.patch(f"/api/admin/staff/{other_owner}", json={"password": PASSWORD}, headers=headers).status_code == 403


@pytest.mark.parametrize("mutation", [{"active": False}, {"role": "order_manager"}, {"password": PASSWORD}])
def test_account_changes_revoke_existing_sessions(security, mutation):
    app, _, _, _ = security
    owner, employee = app.test_client(), app.test_client()
    _, headers = login(owner)
    staff_id = create(owner, headers).json["id"]
    assert login(employee, "cataloger", OTHER_PASSWORD)[0].status_code == 200
    assert employee.get("/api/admin/security/me").status_code == 200
    result = owner.patch(f"/api/admin/staff/{staff_id}", json=mutation, headers=headers)
    assert result.status_code == 200
    assert employee.get("/api/admin/security/me").status_code == 401


def test_revoke_cannot_target_another_staff_session(security):
    app, _, _, _ = security
    owner, employee = app.test_client(), app.test_client()
    owner_login, headers = login(owner)
    owner_session = owner_login.json["principal"]["session_id"]
    create(owner, headers)
    _, employee_headers = login(employee, "cataloger", OTHER_PASSWORD)
    assert employee.delete(f"/api/admin/security/sessions/{owner_session}", headers=employee_headers).status_code == 404
    assert owner.get("/api/admin/security/me").status_code == 200
    assert owner.delete(f"/api/admin/security/sessions/{owner_session}", headers=headers).status_code == 200
    assert owner.get("/api/admin/security/me").status_code == 401


def test_expired_and_logged_out_tokens_cannot_be_replayed(security):
    app, _, _, clock = security
    with app.test_client() as client:
        login(client)
        with client.session_transaction() as cookie:
            old_token = cookie["staff_token"]
        client.post("/test-logout")
        with client.session_transaction() as cookie:
            cookie["staff_token"] = old_token
        assert client.get("/api/admin/security/me").status_code == 401
        login(client)
        clock[0] += 61
        assert client.get("/api/admin/security/me").status_code == 401


def test_login_failures_throttled_and_audit_contains_no_credentials(security):
    app, _, connect, clock = security
    with app.test_client() as client:
        for _ in range(5):
            assert login(client, password="bad-password")[0].status_code == 401
        assert login(client)[0].status_code == 429
        clock[0] += 901
        assert login(client)[0].status_code == 200
        with connect() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM staff_login_events")]
            audit = [dict(r) for r in c.execute("SELECT * FROM audit_log")]
            stored = json.dumps(rows + audit)
            assert PASSWORD not in stored
            assert "bad-password" not in stored
            assert "password_hash" not in stored
            assert {r["outcome"] for r in rows} == {"denied", "throttled", "success"}


def test_totp_rfc_vector():
    assert totp_code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 1) == "287082"


def test_bootstrap_mfa_enrollment_and_replay_protection(security):
    app, access, connect, clock = security
    with app.test_client() as client:
        _, headers = login(client)
        assert client.post("/api/admin/security/mfa/enroll", json={"password": "bad"}, headers=headers).status_code == 401
        response = client.post("/api/admin/security/mfa/enroll", json={"password": PASSWORD}, headers=headers)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        secret = response.json["secret"]
        code = totp_code(secret, clock[0] // 30)
        confirm = client.post("/api/admin/security/mfa/confirm", json={"code": code}, headers=headers)
        assert confirm.status_code == 200
        assert client.get("/api/admin/security/me").json["mfa_enabled"] is True
        client.post("/test-logout")
        assert login(client)[0].status_code == 401
        assert login(client, otp=code)[0].status_code == 401  # Confirmation consumes its step.
        clock[0] += 30
        fresh_code = totp_code(secret, clock[0] // 30)
        assert login(client, otp=fresh_code)[0].status_code == 200
        client.post("/test-logout")
        assert login(client, otp=fresh_code)[0].status_code == 401
        with connect() as c:
            logs = json.dumps([dict(r) for r in c.execute("SELECT * FROM audit_log")])
            assert secret not in logs
        access.require_mfa = True
        clock[0] += 30
        assert login(client, otp=totp_code(secret, clock[0] // 30))[0].status_code == 200


def test_require_mfa_does_not_allow_bootstrap_bypass(security):
    app, access, _, _ = security
    access.require_mfa = True
    with app.test_client() as client:
        response, _ = login(client)
        assert response.status_code == 403
        assert response.json["error"] == "mfa_enrollment_required"


def test_account_password_change_reauthenticates_and_revokes(security):
    app, _, _, _ = security
    with app.test_client() as owner:
        _, headers = login(owner)
        create(owner, headers)
    with app.test_client() as user:
        _, headers = login(user, "cataloger", OTHER_PASSWORD)
        assert user.post("/api/admin/security/password", json={"password": "bad", "new_password": PASSWORD}, headers=headers).status_code == 401
        assert user.post("/api/admin/security/password", json={"password": OTHER_PASSWORD, "new_password": PASSWORD}, headers=headers).status_code == 200
        assert user.get("/api/admin/security/me").status_code == 401
        assert login(user, "cataloger", OTHER_PASSWORD)[0].status_code == 401
        assert login(user, "cataloger", PASSWORD)[0].status_code == 200


def test_invalid_account_fields_are_rejected(security):
    app, _, _, _ = security
    with app.test_client() as client:
        _, headers = login(client)
        assert create(client, headers, "owner").status_code == 400
        assert create(client, headers, "x", "catalog_manager").status_code == 400
        assert create(client, headers, "valid", "not-a-role").status_code == 400
        staff_id = create(client, headers).json["id"]
        assert client.patch(f"/api/admin/staff/{staff_id}", json={"active": "false"}, headers=headers).status_code == 400
        assert client.patch(f"/api/admin/staff/{staff_id}", json={"token_hash": "new"}, headers=headers).status_code == 400
        assert client.patch(f"/api/admin/staff/{staff_id}", json={"role": ["owner"]}, headers=headers).status_code == 400


def test_malformed_username_cannot_alias_a_real_invalid_account(security):
    app, _, _, _ = security
    owner = app.test_client()
    _, headers = login(owner)
    assert create(owner, headers, "invalid").status_code == 201
    user = app.test_client()
    assert login(user, "!!!", OTHER_PASSWORD)[0].status_code == 401
    assert login(user, "invalid", OTHER_PASSWORD)[0].status_code == 200


def test_staff_rotation_preserves_verified_shopper_keys_only(security):
    app, _, _, _ = security
    user = app.test_client()
    shopper = {"guest_id": "synthetic-shopper-identity", "max_guest_id": "max_12345",
               "max_user_id": 12345, "max_auth_date": 1800000000,
               "public_csrf": "synthetic-public-csrf"}
    with user.session_transaction() as cookie:
        cookie.update(shopper)
        cookie["admin_csrf"] = "old-staff-csrf"
        cookie["unclassified_privilege"] = True
    assert login(user)[0].status_code == 200
    with user.session_transaction() as cookie:
        assert all(cookie[key] == value for key, value in shopper.items())
        assert cookie["admin_csrf"] != "old-staff-csrf"
        assert "unclassified_privilege" not in cookie
    user.post("/test-logout")
    with user.session_transaction() as cookie:
        assert dict(cookie) == shopper


def test_request_cache_does_not_nest_locked_transactions(security):
    app, access, connect, _ = security
    @app.get("/test-cache")
    def cached_actor():
        principal = access.current_principal()
        with connect() as c:
            c.execute("SELECT 1")
            assert access.current_principal() == principal
            return {"actor": access.actor()}
    client = app.test_client()
    assert login(client)[0].status_code == 200
    assert client.get("/test-cache").json == {"actor": "staff:bootstrap"}
    # A different request must revalidate the registry instead of using a
    # process/global cached principal after revocation.
    with connect() as c:
        c.execute("UPDATE staff_sessions SET revoked_at=1")
    assert client.get("/api/admin/security/me").status_code == 401


def test_reauthentication_failures_are_committed_and_throttled(security):
    app, _, connect, clock = security
    client = app.test_client()
    _, headers = login(client)
    for _ in range(5):
        assert client.post("/api/admin/security/mfa/enroll", json={"password": "wrong"}, headers=headers).status_code == 401
    assert client.post("/api/admin/security/mfa/enroll", json={"password": PASSWORD}, headers=headers).status_code == 429
    with connect() as c:
        assert c.execute("SELECT MAX(failures) FROM staff_login_guards").fetchone()[0] == 5
    clock[0] += 901
    # This fixture's staff sessions expire in 60 seconds; authenticate again.
    _, headers = login(client)
    assert client.post("/api/admin/security/mfa/enroll", json={"password": PASSWORD}, headers=headers).status_code == 200


def test_mfa_confirmation_has_a_committed_attempt_limit(security):
    app, _, connect, clock = security
    client = app.test_client()
    _, headers = login(client)
    enrollment = client.post("/api/admin/security/mfa/enroll", json={"password": PASSWORD}, headers=headers)
    actual = totp_code(enrollment.json["secret"], clock[0] // 30)
    wrong = "000000" if actual != "000000" else "111111"
    # Test all three accepted windows to avoid a rare accidental match.
    accepted = {totp_code(enrollment.json["secret"], clock[0] // 30 + offset) for offset in (-1, 0, 1)}
    wrong = next(f"{value:06d}" for value in range(10) if f"{value:06d}" not in accepted)
    for _ in range(5):
        assert client.post("/api/admin/security/mfa/confirm", json={"code": wrong}, headers=headers).status_code == 401
    response = client.post("/api/admin/security/mfa/confirm", json={"code": actual}, headers=headers)
    assert response.status_code == 429
    assert response.json["error"] == "mfa_confirmation_throttled"
    with connect() as c:
        assert c.execute("SELECT enabled FROM staff_mfa WHERE staff_id='bootstrap'").fetchone()[0] == 0


def test_require_mfa_revokes_unenrolled_privileged_session_on_next_request(security):
    app, access, _, _ = security
    client = app.test_client()
    assert login(client)[0].status_code == 200
    access.require_mfa = True
    assert client.get("/api/admin/security/me").status_code == 401
