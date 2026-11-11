CREATE TABLE IF NOT EXISTS provider_connections (
 provider TEXT PRIMARY KEY, ciphertext TEXT NOT NULL,
 verified_digest TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL DEFAULT '',
 identity TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS provider_deliveries (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, state TEXT NOT NULL,
 payload_digest TEXT NOT NULL, remote_id TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_events (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, event_type TEXT NOT NULL, received_at TEXT NOT NULL
);
