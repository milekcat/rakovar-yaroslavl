-- Baseline schema; CREATE IF NOT EXISTS preserves existing preview records.
CREATE TABLE IF NOT EXISTS products (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
          price INTEGER NOT NULL CHECK(price>=0), unit TEXT NOT NULL,
          stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0), description TEXT NOT NULL DEFAULT '',
          image TEXT NOT NULL DEFAULT 'opt_hero.svg', badge TEXT NOT NULL DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
          image_url TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
          price_verified INTEGER NOT NULL DEFAULT 0, stock_confirmed INTEGER NOT NULL DEFAULT 0,
          weight_label TEXT NOT NULL DEFAULT '', price_on_request INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS orders (
          id TEXT PRIMARY KEY, created_at TEXT NOT NULL, customer_label TEXT NOT NULL,
          contact_label TEXT NOT NULL, delivery_mode TEXT NOT NULL, address_label TEXT NOT NULL,
          items_json TEXT NOT NULL, subtotal_rub INTEGER NOT NULL, discount_rub INTEGER NOT NULL,
          delivery_rub INTEGER NOT NULL, total_rub INTEGER NOT NULL, promo_code TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 1,
          guest_id TEXT NOT NULL DEFAULT '', source_channel TEXT NOT NULL DEFAULT 'web'
        );
        CREATE TABLE IF NOT EXISTS visitors (
          guest_id TEXT PRIMARY KEY, tickets INTEGER NOT NULL DEFAULT 0, points INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, last_daily_claim TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS prizes (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
          stock INTEGER NOT NULL DEFAULT 0, weight INTEGER NOT NULL DEFAULT 1, partner TEXT NOT NULL DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS spins (
          id INTEGER PRIMARY KEY AUTOINCREMENT, guest_id TEXT NOT NULL, prize_id TEXT NOT NULL,
          prize_title TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unclaimed'
        );
        CREATE TABLE IF NOT EXISTS promotions (
          code TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
          discount_type TEXT NOT NULL, discount_value INTEGER NOT NULL, min_order INTEGER NOT NULL DEFAULT 0,
          max_uses INTEGER NOT NULL DEFAULT 0, uses INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
          starts_at TEXT NOT NULL DEFAULT '', ends_at TEXT NOT NULL DEFAULT '',
          ticket_reward INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS contests (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, prize_title TEXT NOT NULL,
          starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, status TEXT NOT NULL,
          max_entries INTEGER NOT NULL DEFAULT 1, rules TEXT NOT NULL DEFAULT '',
          ticket_reward INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS contest_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT, contest_id TEXT NOT NULL REFERENCES contests(id),
          guest_id TEXT NOT NULL, alias TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, UNIQUE(contest_id, guest_id)
        );
        CREATE TABLE IF NOT EXISTS contest_winners (
          id INTEGER PRIMARY KEY AUTOINCREMENT, contest_id TEXT NOT NULL REFERENCES contests(id),
          entry_id INTEGER NOT NULL REFERENCES contest_entries(id), alias TEXT NOT NULL,
          answer TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(contest_id, entry_id)
        );
        CREATE TABLE IF NOT EXISTS content_posts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL,
          channels_json TEXT NOT NULL, scheduled_at TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS site_settings (
          setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, event_name TEXT NOT NULL, guest_id TEXT NOT NULL DEFAULT '',
          metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS integration_health (
          provider TEXT PRIMARY KEY, status TEXT NOT NULL, last_checked TEXT NOT NULL,
          detail TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS ticket_ledger (
          id INTEGER PRIMARY KEY AUTOINCREMENT, guest_id TEXT NOT NULL,
          delta INTEGER NOT NULL, reason TEXT NOT NULL, source_type TEXT NOT NULL,
          source_id TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL, UNIQUE(guest_id,source_type,source_id)
        );
        CREATE INDEX IF NOT EXISTS idx_ticket_ledger_guest ON ticket_ledger(guest_id,id DESC);
        CREATE TABLE IF NOT EXISTS referral_codes (
          code TEXT PRIMARY KEY, owner_guest_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS referral_attributions (
          referred_guest_id TEXT PRIMARY KEY, referrer_guest_id TEXT NOT NULL, code TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, qualified_order_id TEXT NOT NULL DEFAULT '',
          qualified_at TEXT NOT NULL DEFAULT '', referrer_reward INTEGER NOT NULL DEFAULT 0, friend_reward INTEGER NOT NULL DEFAULT 0,
          CHECK(referrer_guest_id <> referred_guest_id)
        );
        CREATE INDEX IF NOT EXISTS idx_referral_referrer ON referral_attributions(referrer_guest_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
          entity TEXT NOT NULL, entity_id TEXT NOT NULL DEFAULT '', details_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );
