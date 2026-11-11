CREATE TABLE IF NOT EXISTS shop_profiles (
 guest_id TEXT PRIMARY KEY, ciphertext TEXT NOT NULL DEFAULT '', favorites_json TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS shop_accounts (
 id TEXT PRIMARY KEY, guest_id TEXT NOT NULL UNIQUE, email_digest TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shop_sessions (
 token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES shop_accounts(id), expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS shop_inventory (
 product_id TEXT PRIMARY KEY REFERENCES products(id), quantity_milli INTEGER NOT NULL DEFAULT 0,
 tracked INTEGER NOT NULL DEFAULT 0, threshold_milli INTEGER NOT NULL DEFAULT 3000,
 step_milli INTEGER NOT NULL DEFAULT 1000, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shop_stock_ledger (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL, delta_milli INTEGER NOT NULL,
 reason TEXT NOT NULL, reference TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(product_id,reference)
);
CREATE TABLE IF NOT EXISTS shop_order_details (
 order_id TEXT PRIMARY KEY REFERENCES orders(id), ciphertext TEXT NOT NULL,
 payment_method TEXT NOT NULL, bonus_spent INTEGER NOT NULL DEFAULT 0,
 bonus_earned INTEGER NOT NULL DEFAULT 0, inventory_released INTEGER NOT NULL DEFAULT 0,
 rules_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS shop_bonus_ledger (
 id TEXT PRIMARY KEY, guest_id TEXT NOT NULL, delta INTEGER NOT NULL,
 reason TEXT NOT NULL, reference TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shop_notifications (
 id TEXT PRIMARY KEY, guest_id TEXT NOT NULL DEFAULT '', order_id TEXT NOT NULL DEFAULT '',
 audience TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 read_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shop_outbox (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 remote_id TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shop_notice_audience ON shop_notifications(audience,guest_id,created_at);
CREATE INDEX IF NOT EXISTS idx_shop_bonus_guest ON shop_bonus_ledger(guest_id,created_at);
