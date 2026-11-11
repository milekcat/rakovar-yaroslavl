-- Additive staff identities, revocable sessions, idempotency receipts and webhook leases.

CREATE TABLE IF NOT EXISTS staff_accounts (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS staff_sessions (
                id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, staff_id TEXT NOT NULL,
                credential_version TEXT NOT NULL, created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL, revoked_at INTEGER NOT NULL DEFAULT 0);

CREATE INDEX IF NOT EXISTS idx_staff_sessions_identity ON staff_sessions(staff_id,expires_at);

CREATE TABLE IF NOT EXISTS staff_mfa (
                staff_id TEXT PRIMARY KEY, secret TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 0,
                pending_secret TEXT NOT NULL DEFAULT '', pending_until INTEGER NOT NULL DEFAULT 0,
                last_counter INTEGER NOT NULL DEFAULT -1);

CREATE TABLE IF NOT EXISTS staff_login_events (
                id TEXT PRIMARY KEY, subject_hash TEXT NOT NULL, outcome TEXT NOT NULL, created_at INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS staff_login_guards (
                subject_hash TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, locked_until INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS operation_receipts (
        guest_id TEXT NOT NULL, operation TEXT NOT NULL, request_key TEXT NOT NULL,
        request_digest TEXT NOT NULL, response_json TEXT NOT NULL,
        response_status INTEGER NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(guest_id, operation, request_key));

CREATE TABLE IF NOT EXISTS order_status_history (
        id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
        previous_status TEXT NOT NULL, new_status TEXT NOT NULL,
        actor TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE INDEX IF NOT EXISTS idx_order_history ON order_status_history(order_id,created_at);

CREATE TABLE IF NOT EXISTS max_webhook_events (
        event_hash TEXT PRIMARY KEY, received_at TEXT NOT NULL, processed_at TEXT);

CREATE TABLE IF NOT EXISTS max_webhook_leases (
        event_hash TEXT PRIMARY KEY REFERENCES max_webhook_events(event_hash),
        lease_token TEXT NOT NULL, lease_until INTEGER NOT NULL);
