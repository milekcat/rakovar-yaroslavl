CREATE TABLE IF NOT EXISTS shop_catalog_overrides (
 product_id TEXT PRIMARY KEY REFERENCES products(id), fields_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shop_orders_guest ON orders(guest_id,created_at);
CREATE INDEX IF NOT EXISTS idx_shop_outbox_pending ON shop_outbox(state,created_at);
