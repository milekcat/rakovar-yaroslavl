"""Individual staff identities, revocable sessions and explicit admin permissions.

No trust is placed in the legacy ``session['admin']`` boolean. The optional
environment password remains a bootstrap owner, backed by the same session/MFA
checks as database accounts. Passwords, MFA seeds and session tokens are never
included in audit records or account responses.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
import uuid
from functools import wraps

from flask import g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash


ROLE_PERMISSIONS = {
    "owner": {"*"},
    "admin": {"shell", "dashboard.read", "orders.read", "orders.write", "catalog.read", "catalog.write", "promotions.read", "promotions.write", "games.read", "games.write", "content.read", "content.write", "integrations.read", "analytics.read", "loyalty.read", "loyalty.write", "settings.read", "settings.write", "audit.read", "staff.manage"},
    "store_manager": {"shell", "dashboard.read", "orders.read", "orders.write", "catalog.read", "catalog.write", "promotions.read", "games.read", "loyalty.read", "settings.read"},
    "catalog_manager": {"shell", "catalog.read", "catalog.write"},
    "warehouse_operator": {"shell", "catalog.read"},
    "order_manager": {"shell", "orders.read", "orders.write", "catalog.read"},
    "marketing_manager": {"shell", "promotions.read", "promotions.write", "games.read", "games.write", "content.read", "content.write", "integrations.read", "loyalty.read", "loyalty.write", "analytics.read"},
    "content_editor": {"shell", "content.read", "content.write", "catalog.read"},
    "courier": {"shell"},
    "customer_support": {"shell", "orders.read", "catalog.read"},
    "finance_analyst": {"shell", "dashboard.read", "orders.read", "analytics.read", "loyalty.read"},
    "partner": {"shell"},
}
PRIVILEGED_ROLES = {"owner", "admin"}
SHOPPER_SESSION_KEYS = {"guest_id", "max_guest_id", "max_user_id", "max_auth_date", "public_csrf"}

# An unknown endpoint is denied even for owners. New routes must be reviewed and
# entered here; role='owner' is not a bypass around an unclassified route.
ENDPOINT_PERMISSIONS = {
    "admin_panel": "shell", "admin_logout": "shell",
    "admin_dashboard": "dashboard.read",
    "admin_orders": "orders.read", "admin_order_update": "orders.write", "admin_order_history": "orders.read",
    "admin_products": "catalog.read", "admin_product_create": "catalog.write", "admin_product_update": "catalog.write",
    "admin_promotions": "promotions.read", "admin_promotion_create": "promotions.write", "admin_promotion_update": "promotions.write",
    "admin_prizes": "games.read", "admin_prize_create": "games.write", "admin_prize_update": "games.write",
    "admin_spins": "games.read", "admin_spin_update": "games.write",
    "admin_contests": "games.read", "admin_contest_create": "games.write", "admin_contest_update": "games.write", "admin_contest_draw": "games.write",
    "admin_settings": "settings.read", "admin_settings_update": "settings.write",
    "admin_content": "content.read", "admin_content_create": "content.write", "admin_content_update": "content.write", "admin_content_publish": "content.write",
    "admin_integrations": "integrations.read", "admin_analytics": "analytics.read",
    "admin_loyalty_ledger": "loyalty.read", "admin_loyalty_rules_update": "loyalty.write", "admin_loyalty_award": "loyalty.write",
    "admin_referrals": "loyalty.read", "admin_referral_rules_update": "loyalty.write", "admin_audit": "audit.read",
}


class StaffError(ValueError):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def totp_code(secret: str, counter: int) -> str:
    """RFC 6238 SHA-1, six digits, 30-second time step (counter passed explicitly)."""
    raw = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(raw, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff
    return f"{number % 1_000_000:06d}"


def _matched_counter(secret, supplied, now, previous=-1):
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9]{6}", supplied):
        return None
    for counter in (int(now) // 30, int(now) // 30 - 1, int(now) // 30 + 1):
        if counter > previous and hmac.compare_digest(totp_code(secret, counter), supplied):
            return counter
    return None


class StaffAccess:
    def __init__(self, app, connect_db, *, bootstrap_hash="", require_mfa=False,
                 session_seconds=43200, now=time.time):
        self.app, self.connect_db = app, connect_db
        self.bootstrap_hash, self.require_mfa = bootstrap_hash, require_mfa
        self.session_seconds, self.now = int(session_seconds), now
        self._dummy_hash = generate_password_hash(secrets.token_urlsafe(32))
        self.init_schema()

    def init_schema(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS staff_accounts (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS staff_sessions (
                id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, staff_id TEXT NOT NULL,
                credential_version TEXT NOT NULL, created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL, revoked_at INTEGER NOT NULL DEFAULT 0)""",
            "CREATE INDEX IF NOT EXISTS idx_staff_sessions_identity ON staff_sessions(staff_id,expires_at)",
            """CREATE TABLE IF NOT EXISTS staff_mfa (
                staff_id TEXT PRIMARY KEY, secret TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 0,
                pending_secret TEXT NOT NULL DEFAULT '', pending_until INTEGER NOT NULL DEFAULT 0,
                last_counter INTEGER NOT NULL DEFAULT -1)""",
            """CREATE TABLE IF NOT EXISTS staff_login_events (
                id TEXT PRIMARY KEY, subject_hash TEXT NOT NULL, outcome TEXT NOT NULL, created_at INTEGER NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS staff_login_guards (
                subject_hash TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, locked_until INTEGER NOT NULL DEFAULT 0)""",
        ]
        with self.connect_db() as c:
            for statement in statements:
                c.execute(statement)

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _username(value):
        value = str(value or "owner").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", value):
            raise StaffError("invalid_username")
        return value

    @staticmethod
    def _password(value):
        if not isinstance(value, str) or len(value) < 12 or len(value) > 256:
            raise StaffError("password_length_12_to_256")
        return value

    def _bootstrap_version(self):
        return hashlib.sha256(self.bootstrap_hash.encode()).hexdigest()

    def _audit(self, c, actor, action, entity_id="", detail=None):
        # The containing application owns this append-only journal.
        c.execute("INSERT INTO audit_log(actor,action,entity,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?)",
                  (actor, action, "staff", entity_id, json.dumps(detail or {}),
                   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now()))))

    def _login_event(self, c, subject, outcome):
        c.execute("INSERT INTO staff_login_events(id,subject_hash,outcome,created_at) VALUES(?,?,?,?)",
                  (uuid.uuid4().hex, subject, outcome, int(self.now())))

    def _record_failure(self, c, subject):
        c.execute("INSERT INTO staff_login_guards(subject_hash,failures,locked_until) VALUES(?,0,0) ON CONFLICT(subject_hash) DO NOTHING", (subject,))
        c.execute("UPDATE staff_login_guards SET failures=failures+1 WHERE subject_hash=?", (subject,))
        count = c.execute("SELECT failures FROM staff_login_guards WHERE subject_hash=?", (subject,)).fetchone()["failures"]
        if count >= 5:
            c.execute("UPDATE staff_login_guards SET locked_until=? WHERE subject_hash=?", (int(self.now()) + 900, subject))
        self._login_event(c, subject, "denied")

    def login(self, username, password, otp=""):
        """Authenticate and rotate cookie/session ID. Raises StaffError on failure."""
        try:
            username = self._username(username)
        except StaffError:
            # Never reinterpret malformed input as a real account named invalid.
            username = ""
        subject = hashlib.sha256(username.encode()).hexdigest()
        failure = None
        with self.connect_db() as c:
            guard = c.execute("SELECT * FROM staff_login_guards WHERE subject_hash=?", (subject,)).fetchone()
            if guard and guard["locked_until"] > int(self.now()):
                self._login_event(c, subject, "throttled")
                failure = StaffError("login_throttled", 429)
            else:
                if guard and guard["locked_until"]:
                    c.execute("UPDATE staff_login_guards SET failures=0,locked_until=0 WHERE subject_hash=?", (subject,))
                row = c.execute("SELECT * FROM staff_accounts WHERE username=?", (username,)).fetchone()
                if username == "owner" and self.bootstrap_hash:
                    identity, role, version, password_hash = "bootstrap", "owner", self._bootstrap_version(), self.bootstrap_hash
                    active = True
                elif row:
                    identity, role, version, password_hash = row["id"], row["role"], str(row["version"]), row["password_hash"]
                    active = bool(row["active"]) and role in ROLE_PERMISSIONS
                else:
                    identity, role, version, password_hash, active = "", "", "", self._dummy_hash, False
                valid_password = isinstance(password, str) and len(password) <= 256 and check_password_hash(password_hash, password)
                mfa = c.execute("SELECT * FROM staff_mfa WHERE staff_id=?", (identity,)).fetchone() if identity else None
                if not valid_password or not active:
                    self._record_failure(c, subject)
                    failure = StaffError("invalid_credentials", 401)
                elif mfa and mfa["enabled"]:
                    counter = _matched_counter(mfa["secret"], otp, self.now(), mfa["last_counter"])
                    if counter is None or c.execute("UPDATE staff_mfa SET last_counter=? WHERE staff_id=? AND last_counter<?", (counter, identity, counter)).rowcount != 1:
                        self._record_failure(c, subject)
                        failure = StaffError("mfa_required_or_invalid", 401)
                elif self.require_mfa and role in PRIVILEGED_ROLES:
                    self._login_event(c, subject, "mfa_enrollment_required")
                    failure = StaffError("mfa_enrollment_required", 403)
                if failure is None:
                    token, session_id = secrets.token_urlsafe(48), uuid.uuid4().hex
                    now = int(self.now())
                    c.execute("INSERT INTO staff_sessions(id,token_hash,staff_id,credential_version,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                              (session_id, self._token_hash(token), identity, version, now, now + self.session_seconds))
                    c.execute("DELETE FROM staff_login_guards WHERE subject_hash=?", (subject,))
                    self._login_event(c, subject, "success")
                    self._audit(c, f"staff:{identity}", "login", identity)
        if failure:
            raise failure
        self.logout()  # Revoke any previous session before rotating its cookie.
        session["staff_token"] = token
        session["admin"] = True  # Presentation compatibility only; never authorization.
        session["admin_csrf"] = secrets.token_urlsafe(32)
        session.permanent = True
        return self.current_principal()

    def current_principal(self):
        token = session.get("staff_token")
        cache = getattr(g, "_rakovar_staff_identity", None)
        if cache and cache[0] is self and cache[1] == token:
            return cache[2]
        principal = self._load_principal(token)
        # One registry read per request. This avoids opening another write
        # transaction from audit() while the business transaction holds a lock.
        g._rakovar_staff_identity = (self, token, principal)
        return principal

    def _load_principal(self, token):
        if not isinstance(token, str) or not 40 <= len(token) <= 128:
            return None
        with self.connect_db() as c:
            row = c.execute("SELECT * FROM staff_sessions WHERE token_hash=? AND revoked_at=0 AND expires_at>?", (self._token_hash(token), int(self.now()))).fetchone()
            if not row:
                return None
            if row["staff_id"] == "bootstrap":
                if not self.bootstrap_hash or not hmac.compare_digest(row["credential_version"], self._bootstrap_version()):
                    return None
                username, role = "owner", "owner"
            else:
                staff = c.execute("SELECT * FROM staff_accounts WHERE id=? AND active=1", (row["staff_id"],)).fetchone()
                if not staff or str(staff["version"]) != row["credential_version"] or staff["role"] not in ROLE_PERMISSIONS:
                    return None
                username, role = staff["username"], staff["role"]
            mfa = c.execute("SELECT enabled FROM staff_mfa WHERE staff_id=?", (row["staff_id"],)).fetchone()
            if self.require_mfa and role in PRIVILEGED_ROLES and not (mfa and mfa["enabled"]):
                return None
            return {"id": row["staff_id"], "username": username, "role": role,
                    "session_id": row["id"], "mfa_enabled": bool(mfa and mfa["enabled"]),
                    "permissions": sorted(ROLE_PERMISSIONS[role])}

    def has_permission(self, principal, permission):
        return bool(principal and ("*" in ROLE_PERMISSIONS.get(principal["role"], set()) or permission in ROLE_PERMISSIONS.get(principal["role"], set())))

    def allowed(self, endpoint, principal=None):
        permission = ENDPOINT_PERMISSIONS.get(endpoint)
        return bool(permission and self.has_permission(principal or self.current_principal(), permission))

    def actor(self):
        principal = self.current_principal()
        return f"staff:{principal['id']}" if principal else "anonymous"

    def logout(self):
        token = session.get("staff_token")
        if isinstance(token, str):
            with self.connect_db() as c:
                c.execute("UPDATE staff_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at=0", (int(self.now()), self._token_hash(token)))
        # Staff and shopper currently share one signed cookie. Rotate staff
        # authority without discarding already verified shopper identity.
        shopper = {key: session[key] for key in SHOPPER_SESSION_KEYS if key in session}
        session.clear()
        session.update(shopper)
        g.pop("_rakovar_staff_identity", None)

    def _reauth(self, principal, password):
        # Commit failed attempts before raising, rather than rolling them back
        # with the rejected security-settings transaction.
        subject = hashlib.sha256(f"reauth:{principal['id']}".encode()).hexdigest()
        failure = None
        with self.connect_db() as c:
            guard = c.execute("SELECT * FROM staff_login_guards WHERE subject_hash=?", (subject,)).fetchone()
            if guard and guard["locked_until"] > int(self.now()):
                self._login_event(c, subject, "throttled")
                failure = StaffError("reauthentication_throttled", 429)
            else:
                if guard and guard["locked_until"]:
                    c.execute("DELETE FROM staff_login_guards WHERE subject_hash=?", (subject,))
                if principal["id"] == "bootstrap":
                    password_hash = self.bootstrap_hash
                else:
                    row = c.execute("SELECT password_hash FROM staff_accounts WHERE id=? AND active=1", (principal["id"],)).fetchone()
                    password_hash = row["password_hash"] if row else self._dummy_hash
                if not isinstance(password, str) or len(password) > 256 or not check_password_hash(password_hash, password):
                    self._record_failure(c, subject)
                    failure = StaffError("reauthentication_failed", 401)
                else:
                    c.execute("DELETE FROM staff_login_guards WHERE subject_hash=?", (subject,))
        if failure:
            raise failure

    def register_routes(self, require_csrf):
        def protected(permission="shell"):
            def decorate(fn):
                @wraps(fn)
                def wrapped(*args, **kwargs):
                    principal = self.current_principal()
                    if not principal:
                        return jsonify(error="admin_auth_required"), 401
                    if not self.has_permission(principal, permission):
                        return jsonify(error="permission_denied"), 403
                    if request.method not in {"GET", "HEAD", "OPTIONS"}:
                        require_csrf()
                    try:
                        return fn(principal, *args, **kwargs)
                    except StaffError as exc:
                        return jsonify(error=exc.code), exc.status
                return wrapped
            return decorate

        def body():
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise StaffError("invalid_json")
            return data

        @protected()
        def me(principal):
            return jsonify(principal)

        @protected("staff.manage")
        def staff_list(principal):
            with self.connect_db() as c:
                rows = [dict(r) for r in c.execute("SELECT id,username,role,active,created_at FROM staff_accounts ORDER BY username")]
                enabled = {r["staff_id"] for r in c.execute("SELECT staff_id FROM staff_mfa WHERE enabled=1")}
            for row in rows:
                row["mfa_enabled"] = row["id"] in enabled
            return jsonify(accounts=rows, roles=sorted(ROLE_PERMISSIONS), bootstrap_owner=bool(self.bootstrap_hash))

        @protected("staff.manage")
        def staff_create(principal):
            data = body()
            username, role = self._username(data.get("username")), str(data.get("role", ""))
            password = self._password(data.get("password"))
            if role not in ROLE_PERMISSIONS or username == "owner":
                raise StaffError("invalid_role_or_reserved_username")
            if principal["role"] != "owner" and role in PRIVILEGED_ROLES:
                raise StaffError("owner_required", 403)
            staff_id = uuid.uuid4().hex
            with self.connect_db() as c:
                cur = c.execute("INSERT INTO staff_accounts(id,username,password_hash,role,active,created_at) VALUES(?,?,?,?,1,?) ON CONFLICT(username) DO NOTHING",
                                (staff_id, username, generate_password_hash(password), role, int(self.now())))
                if cur.rowcount != 1:
                    raise StaffError("username_exists", 409)
                self._audit(c, f"staff:{principal['id']}", "create_account", staff_id, {"role": role})
            return jsonify(id=staff_id, username=username, role=role), 201

        @protected("staff.manage")
        def staff_update(principal, staff_id):
            data = body()
            if not data or set(data) - {"active", "role", "password"}:
                raise StaffError("invalid_account_fields")
            if staff_id == principal["id"]:
                raise StaffError("use_personal_security_settings", 409)
            with self.connect_db() as c:
                staff = c.execute("SELECT * FROM staff_accounts WHERE id=?", (staff_id,)).fetchone()
                if not staff:
                    raise StaffError("staff_not_found", 404)
                role = data.get("role", staff["role"])
                if not isinstance(role, str) or role not in ROLE_PERMISSIONS:
                    raise StaffError("invalid_role")
                if principal["role"] != "owner" and (role in PRIVILEGED_ROLES or staff["role"] in PRIVILEGED_ROLES):
                    raise StaffError("owner_required", 403)
                active = data.get("active", bool(staff["active"]))
                if not isinstance(active, bool):
                    raise StaffError("active_must_be_boolean")
                password_hash = generate_password_hash(self._password(data["password"])) if "password" in data else staff["password_hash"]
                c.execute("UPDATE staff_accounts SET role=?,active=?,password_hash=?,version=version+1 WHERE id=?", (role, int(active), password_hash, staff_id))
                c.execute("UPDATE staff_sessions SET revoked_at=? WHERE staff_id=? AND revoked_at=0", (int(self.now()), staff_id))
                self._audit(c, f"staff:{principal['id']}", "update_account", staff_id, {"role": role, "active": active, "password_reset": "password" in data})
            return jsonify(status="updated")

        @protected()
        def sessions_list(principal):
            with self.connect_db() as c:
                rows = [dict(r) for r in c.execute("SELECT id,created_at,expires_at,revoked_at FROM staff_sessions WHERE staff_id=? ORDER BY created_at DESC LIMIT 100", (principal["id"],))]
            for row in rows:
                row["current"] = row["id"] == principal["session_id"]
            return jsonify(sessions=rows)

        @protected()
        def session_revoke(principal, session_id):
            with self.connect_db() as c:
                cur = c.execute("UPDATE staff_sessions SET revoked_at=? WHERE id=? AND staff_id=? AND revoked_at=0", (int(self.now()), session_id, principal["id"]))
                if not cur.rowcount:
                    raise StaffError("session_not_found", 404)
                self._audit(c, f"staff:{principal['id']}", "revoke_session", principal["id"])
            if session_id == principal["session_id"]:
                self.logout()
            return jsonify(status="revoked")

        @protected()
        def password_change(principal):
            data = body()
            if principal["id"] == "bootstrap":
                raise StaffError("bootstrap_password_managed_in_environment", 409)
            password = self._password(data.get("new_password"))
            self._reauth(principal, data.get("password"))
            with self.connect_db() as c:
                c.execute("UPDATE staff_accounts SET password_hash=?,version=version+1 WHERE id=?", (generate_password_hash(password), principal["id"]))
                c.execute("UPDATE staff_sessions SET revoked_at=? WHERE staff_id=? AND revoked_at=0", (int(self.now()), principal["id"]))
                self._audit(c, f"staff:{principal['id']}", "change_password", principal["id"])
            self.logout()
            return jsonify(status="password_changed", login_required=True)

        @protected()
        def mfa_enroll(principal):
            data = body()
            self._reauth(principal, data.get("password"))
            with self.connect_db() as c:
                existing = c.execute("SELECT enabled FROM staff_mfa WHERE staff_id=?", (principal["id"],)).fetchone()
                if existing and existing["enabled"]:
                    raise StaffError("mfa_already_enabled", 409)
                secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
                c.execute("INSERT INTO staff_mfa(staff_id,pending_secret,pending_until) VALUES(?,?,?) ON CONFLICT(staff_id) DO UPDATE SET pending_secret=excluded.pending_secret,pending_until=excluded.pending_until", (principal["id"], secret, int(self.now()) + 600))
                self._audit(c, f"staff:{principal['id']}", "start_mfa_enrollment", principal["id"])
            # Deliberately available only to this reauthenticated, CSRF-protected
            # session. The caller must never log/cache this provisioning response.
            return jsonify(secret=secret, algorithm="SHA1", digits=6, period=30, expires_in=600)

        @protected()
        def mfa_confirm(principal):
            data = body()
            subject = hashlib.sha256(f"mfa-enroll:{principal['id']}".encode()).hexdigest()
            with self.connect_db() as c:
                guard = c.execute("SELECT * FROM staff_login_guards WHERE subject_hash=?", (subject,)).fetchone()
                if guard and guard["locked_until"] > int(self.now()):
                    self._login_event(c, subject, "throttled")
                    return jsonify(error="mfa_confirmation_throttled"), 429
                if guard and guard["locked_until"]:
                    c.execute("DELETE FROM staff_login_guards WHERE subject_hash=?", (subject,))
                mfa = c.execute("SELECT * FROM staff_mfa WHERE staff_id=?", (principal["id"],)).fetchone()
                if not mfa or not mfa["pending_secret"] or mfa["pending_until"] <= int(self.now()) or mfa["enabled"]:
                    raise StaffError("mfa_enrollment_expired", 409)
                counter = _matched_counter(mfa["pending_secret"], data.get("code"), self.now())
                if counter is None:
                    self._record_failure(c, subject)
                    return jsonify(error="invalid_mfa_code"), 401
                cur = c.execute("UPDATE staff_mfa SET secret=pending_secret,pending_secret='',pending_until=0,enabled=1,last_counter=? WHERE staff_id=? AND pending_secret=? AND enabled=0", (counter, principal["id"], mfa["pending_secret"]))
                if cur.rowcount != 1:
                    raise StaffError("mfa_enrollment_changed", 409)
                c.execute("UPDATE staff_sessions SET revoked_at=? WHERE staff_id=? AND id<>? AND revoked_at=0", (int(self.now()), principal["id"], principal["session_id"]))
                c.execute("DELETE FROM staff_login_guards WHERE subject_hash=?", (subject,))
                self._audit(c, f"staff:{principal['id']}", "enable_mfa", principal["id"])
            g.pop("_rakovar_staff_identity", None)
            return jsonify(status="mfa_enabled")

        @protected("staff.manage")
        def login_events(principal):
            with self.connect_db() as c:
                rows = [dict(r) for r in c.execute("SELECT id,subject_hash,outcome,created_at FROM staff_login_events ORDER BY created_at DESC LIMIT 200")]
            return jsonify(events=rows)

        routes = [
            ("/api/admin/security/me", "staff_security_me", me, ["GET"]),
            ("/api/admin/staff", "staff_accounts_list", staff_list, ["GET"]),
            ("/api/admin/staff", "staff_accounts_create", staff_create, ["POST"]),
            ("/api/admin/staff/<staff_id>", "staff_accounts_update", staff_update, ["PATCH"]),
            ("/api/admin/security/sessions", "staff_sessions_list", sessions_list, ["GET"]),
            ("/api/admin/security/sessions/<session_id>", "staff_session_revoke", session_revoke, ["DELETE"]),
            ("/api/admin/security/password", "staff_password_change", password_change, ["POST"]),
            ("/api/admin/security/mfa/enroll", "staff_mfa_enroll", mfa_enroll, ["POST"]),
            ("/api/admin/security/mfa/confirm", "staff_mfa_confirm", mfa_confirm, ["POST"]),
            ("/api/admin/security/login-events", "staff_login_events", login_events, ["GET"]),
        ]
        for path, endpoint, fn, methods in routes:
            self.app.add_url_rule(path, endpoint, fn, methods=methods)

        @self.app.after_request
        def staff_cache_headers(response):
            if request.path.startswith("/api/admin/security") or request.path.startswith("/api/admin/staff"):
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"
            return response
