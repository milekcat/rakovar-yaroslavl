"""РАКОВАРЪ demo commerce platform.

Demo mode stores only synthetic order contacts and clearly labels sample data.
Production ordering/payments/social publishing remain disabled until owner setup.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from contextlib import contextmanager
import hmac
import json
import os
import secrets
import time
import sqlite3
from functools import wraps
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from catalog_seed import CATALOG_PRODUCTS, is_non_brand_product
from max_auth import validate_init_data as verify_max_init_data, MaxInitDataError

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("SQLITE_DB_PATH", str(BASE_DIR / "rakovar.sqlite3"))
DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"
MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN", "").strip()
MAX_MINIAPP_URL = os.environ.get("MAX_MINIAPP_URL", "").strip()
MAX_BOT_USERNAME = os.environ.get("MAX_BOT_USERNAME", "id7606139934_5_bot").strip().lstrip("@")
MAX_ADMIN_USER_ID = os.environ.get("MAX_ADMIN_USER_ID", "").strip()
MAX_WEBHOOK_SECRET = os.environ.get("MAX_WEBHOOK_SECRET", "").strip()
LOYALTY_RUB_PER_TICKET = max(100, min(int(os.environ.get("LOYALTY_RUB_PER_TICKET", "1000")), 100000))
PREVIEW_DELIVERY_RUB = max(0, min(int(os.environ.get("PREVIEW_DELIVERY_RUB", "200")), 5000))
PREVIEW_DELIVERY_MIN_RUB = max(0, min(int(os.environ.get("PREVIEW_DELIVERY_MIN_RUB", "1000")), 100000))

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    MAX_CONTENT_LENGTH=256 * 1024,
    PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=12),
)
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
_LOGIN_FAILURES: dict[str, tuple[int, float]] = {}
_RATE_BUCKETS: dict[str, tuple[float, int]] = {}

NOW = lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
TODAY = lambda: dt.datetime.now(dt.timezone.utc).date().isoformat()

SAMPLE_PRIZES = [
    {"id":"prize-5","title":"Скидка 5% на заказ","kind":"coupon","description":"Демонстрационный промокод. Не является действующей акцией.","stock":50,"weight":35,"partner":"РАКОВАРЪ","reward_value":5},
    {"id":"prize-delivery","title":"Бесплатная доставка","kind":"delivery","description":"Пример возможного приза при запуске программы.","stock":10,"weight":20,"partner":"РАКОВАРЪ"},
    {"id":"prize-sauce","title":"Фирменный соус","kind":"gift","description":"Подарок-пример; наличие и состав необходимо подтвердить.","stock":8,"weight":20,"partner":"Партнёрский приз"},
    {"id":"prize-10","title":"Скидка 10% на заказ","kind":"coupon","description":"Демонстрационный промокод. Не является действующей акцией.","stock":5,"weight":10,"partner":"РАКОВАРЪ","reward_value":10},
    {"id":"prize-consolation","title":"+50 баллов клуба","kind":"points","description":"Тестовые баллы демонстрационной программы.","stock":9999,"weight":15,"partner":"РАКОВАРЪ"},
]

SAMPLE_PROMOTIONS = [
    {"code":"WELCOME10","title":"Знакомство с РАКОВАРЪ","description":"Пример скидки для первого заказа.","discount_type":"percent","discount_value":10,"min_order":1500,"max_uses":100,"active":1},
    {"code":"SEA300","title":"Морской бонус","description":"Пример скидки 300 ₽ при заказе от 2 500 ₽.","discount_type":"fixed","discount_value":300,"min_order":2500,"max_uses":50,"active":1},
]

SAMPLE_CONTESTS = [
    {"id":"sea-evening","title":"Мой морской вечер","description":"Поделитесь идеей идеального морского ужина. В демо-версии принимается тестовая заявка без публикации фото и личных данных.","prize_title":"Подарочный сет от РАКОВАРЪ (пример)","starts_at":TODAY(),"ends_at":(dt.date.today()+dt.timedelta(days=21)).isoformat(),"status":"active","max_entries":1,"rules":"Демонстрационный конкурс. До реального запуска организатор утверждает официальные правила, сроки, критерии выбора и порядок выдачи призов."},
]


SITE_DEFAULTS = {
    "hero_title": "Море ближе, чем кажется.",
    "hero_text": "Живые и варёные раки, крабы, креветки, мидии, рыба, авторские сеты и съедобные подарки. Подберём деликатесы для вечера, праздника и особого повода.",
    "hero_cta": "Смотреть меню",
    "promo_title": "Маленький бонус для большого вкуса.",
    "promo_text": "Получайте клубные билеты за подтверждённые покупки и участие в специальных активностях. Тратьте их в игровой гавани РАКОВАРЪ.",
    "footer_notice": "Демонстрационный проект · не является публичной офертой",
    "loyalty_rub_per_ticket": str(LOYALTY_RUB_PER_TICKET),
    "contact_address": "Комсомольская, 14, Ярославль",
    "contact_phone": "+7 (920) 118-57-87",
    "contact_hours": "Магазин: ежедневно 10:00–21:00 · доставка: 11:30–21:00. Время уточняйте при заказе.",
}


@contextmanager
def connect_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def public_catalog_products(c: sqlite3.Connection) -> list[dict]:
    """Return active, brand-relevant items only; keep legacy rows available to admins."""
    rows = c.execute("SELECT * FROM products WHERE active=1 ORDER BY category,title").fetchall()
    return [dict(row) for row in rows if not is_non_brand_product(dict(row))]


def get_loyalty_rate(c: sqlite3.Connection) -> int:
    row = c.execute("SELECT setting_value FROM site_settings WHERE setting_key='loyalty_rub_per_ticket'").fetchone()
    try:
        value = int(row[0]) if row else LOYALTY_RUB_PER_TICKET
    except (TypeError, ValueError):
        value = LOYALTY_RUB_PER_TICKET
    return max(100, min(value, 100000))


def init_db() -> None:
    with connect_db() as c:
        c.executescript("""
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
        """)
        # Additive SQLite migrations keep existing preview databases bootable.
        for table, column, declaration in [
            ("prizes", "reward_value", "INTEGER NOT NULL DEFAULT 0"),
            ("spins", "redemption_code", "TEXT NOT NULL DEFAULT ''"),
            ("products", "image_url", "TEXT NOT NULL DEFAULT ''"),
            ("products", "source_url", "TEXT NOT NULL DEFAULT ''"),
            ("products", "price_verified", "INTEGER NOT NULL DEFAULT 0"),
            ("products", "stock_confirmed", "INTEGER NOT NULL DEFAULT 0"),
            ("products", "weight_label", "TEXT NOT NULL DEFAULT ''"),
            ("products", "price_on_request", "INTEGER NOT NULL DEFAULT 0"),
            ("orders", "guest_id", "TEXT NOT NULL DEFAULT ''"),
            ("orders", "source_channel", "TEXT NOT NULL DEFAULT 'web'"),
            ("promotions", "ticket_reward", "INTEGER NOT NULL DEFAULT 0"),
            ("contests", "ticket_reward", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            existing = {row[1] for row in c.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        if DEMO_MODE:
            seed_row = c.execute("SELECT setting_value FROM site_settings WHERE setting_key='catalog_seed_version'").fetchone()
            if not seed_row or seed_row[0] != "brand-refresh-2026-11-09-v6":
                # Refresh only unverified imported rows; operator-approved prices/stock are preserved.
                for p in CATALOG_PRODUCTS:
                    c.execute("""INSERT INTO products
                        (id,title,category,price,unit,stock,description,image,badge,created_at,image_url,source_url,price_verified,stock_confirmed,weight_label,price_on_request)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET
                          title=excluded.title,category=excluded.category,price=excluded.price,unit=excluded.unit,
                          description=excluded.description,image=excluded.image,badge=excluded.badge,
                          image_url=excluded.image_url,source_url=excluded.source_url,weight_label=excluded.weight_label,
                          price_on_request=excluded.price_on_request
                        WHERE products.price_verified=0 AND products.stock_confirmed=0""",
                        (p['id'],p['title'],p['category'],p['price'],p['unit'],p['stock'],p['description'],p['image'],p['badge'],NOW(),p['image_url'],p['source_url'],0,0,p['weight'],p['price_on_request']))
                c.execute("UPDATE products SET active=0 WHERE id IN ('crayfish-classic','seafood-platter','shrimp-tiger','crayfish-bouquet','seafood-gift')")
                # Old preview databases can retain menu rows that are no longer part of the brand catalog.
                legacy_rows = c.execute("SELECT id,title,category,description,image,badge,image_url FROM products WHERE active=1").fetchall()
                for legacy_row in legacy_rows:
                    if is_non_brand_product(dict(legacy_row)):
                        c.execute("UPDATE products SET active=0 WHERE id=?", (legacy_row["id"],))
                c.execute("UPDATE promotions SET ticket_reward=1 WHERE code IN ('WELCOME10','SEA300') AND ticket_reward=0")
                c.execute("UPDATE contests SET ticket_reward=1 WHERE id='sea-evening' AND ticket_reward=0")
                c.execute("INSERT OR REPLACE INTO site_settings(setting_key,setting_value,updated_at) VALUES('catalog_seed_version',?,?)", ("brand-refresh-2026-11-09-v6", NOW()))
        if DEMO_MODE and c.execute("SELECT COUNT(*) FROM prizes").fetchone()[0] == 0:
            c.executemany("INSERT INTO prizes(id,title,kind,description,stock,weight,partner,reward_value) VALUES(?,?,?,?,?,?,?,?)",
              [(p['id'],p['title'],p['kind'],p['description'],p['stock'],p['weight'],p['partner'],p.get('reward_value',0)) for p in SAMPLE_PRIZES])
        if DEMO_MODE and c.execute("SELECT COUNT(*) FROM promotions").fetchone()[0] == 0:
            c.executemany("INSERT INTO promotions(code,title,description,discount_type,discount_value,min_order,max_uses,active,ticket_reward) VALUES(?,?,?,?,?,?,?,?,?)",
              [(p['code'],p['title'],p['description'],p['discount_type'],p['discount_value'],p['min_order'],p['max_uses'],p['active'],1) for p in SAMPLE_PROMOTIONS])
        if DEMO_MODE and c.execute("SELECT COUNT(*) FROM contests").fetchone()[0] == 0:
            c.executemany("INSERT INTO contests(id,title,description,prize_title,starts_at,ends_at,status,max_entries,rules,ticket_reward) VALUES(?,?,?,?,?,?,?,?,?,?)",
              [(x['id'],x['title'],x['description'],x['prize_title'],x['starts_at'],x['ends_at'],x['status'],x['max_entries'],x['rules'],1) for x in SAMPLE_CONTESTS])
        if DEMO_MODE:
            c.executemany("INSERT OR IGNORE INTO site_settings(setting_key,setting_value,updated_at) VALUES(?,?,?)",
                          [(k,v,NOW()) for k,v in SITE_DEFAULTS.items()])
            # Migrate untouched preview defaults to the refreshed brand copy;
            # preserve values that an administrator has explicitly customized.
            default_migrations = [
                ("hero_title", "РАКОВАРЪ. Морская история со вкусом.", SITE_DEFAULTS["hero_title"]),
                ("hero_text", "Живые и варёные раки, морские деликатесы, авторские сеты и съедобные подарки. Выбирайте любимое, собирайте свой набор и присоединяйтесь к клубу РАКОВАРЪ.", SITE_DEFAULTS["hero_text"]),
                ("hero_cta", "Выбрать продукты", SITE_DEFAULTS["hero_cta"]),
                ("contact_address", "Малый Московский переулок, 1/17, Ярославль", SITE_DEFAULTS["contact_address"]),
                ("contact_hours", "Ежедневно · точное время подтвердить у менеджера", SITE_DEFAULTS["contact_hours"]),
            ]
            for key, old_value, new_value in default_migrations:
                c.execute(
                    "UPDATE site_settings SET setting_value=?,updated_at=? WHERE setting_key=? AND setting_value=?",
                    (new_value, NOW(), key, old_value),
                )


init_db()


def json_body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            if request.path.startswith('/api/'):
                return jsonify(error="admin_auth_required"), 401
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapped


def csrf_token() -> str:
    if "public_csrf" not in session:
        session["public_csrf"] = secrets.token_urlsafe(32)
    return session["public_csrf"]


def csrf_valid() -> bool:
    supplied = request.headers.get("X-CSRF-Token") or json_body().get("csrf_token") or request.form.get("csrf_token")
    expected = session.get("admin_csrf") if (request.path.startswith("/admin") or request.path.startswith("/api/admin")) else session.get("public_csrf")
    return bool(supplied and expected and hmac.compare_digest(str(supplied), str(expected)))


def require_csrf():
    if not csrf_valid():
        abort(400, description="csrf_failed")


def audit(c: sqlite3.Connection, action: str, entity: str, entity_id: str = "", details: dict | None = None):
    c.execute("INSERT INTO audit_log(actor,action,entity,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?)",
              ("admin", action, entity, str(entity_id), json.dumps(details or {}, ensure_ascii=False), NOW()))


def rate_limited(scope: str, limit: int, window_seconds: int = 60) -> bool:
    now = time.monotonic()
    key = f"{scope}:{request.remote_addr or 'unknown'}"
    started, count = _RATE_BUCKETS.get(key, (now, 0))
    if now - started >= window_seconds:
        started, count = now, 0
    if count >= limit:
        _RATE_BUCKETS[key] = (started, count)
        return True
    _RATE_BUCKETS[key] = (started, count + 1)
    return False


def clean_guest_id(value: Any) -> str:
    value = str(value or "")
    # MAX user IDs are numeric and may be shorter than the opaque browser UUID.
    is_max_id = value.startswith("max_") and value[4:].isdigit() and 1 <= len(value[4:]) <= 20
    if (not is_max_id and (len(value) < 12 or len(value) > 80)) or not all(ch.isalnum() or ch in "-_" for ch in value):
        abort(400, description="invalid_guest_id")
    return value


def get_visitor(c: sqlite3.Connection, guest_id: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM visitors WHERE guest_id=?", (guest_id,)).fetchone()
    if row is None:
        # Preview onboarding tickets are synthetic and are never granted in live mode.
        initial_tickets = 3 if DEMO_MODE else 0
        c.execute("INSERT INTO visitors(guest_id,tickets,points,created_at) VALUES(?,?,?,?)",
                  (guest_id, initial_tickets, 0, NOW()))
        if initial_tickets:
            c.execute("INSERT OR IGNORE INTO ticket_ledger(guest_id,delta,reason,source_type,source_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                      (guest_id, initial_tickets, "Стартовые тестовые билеты preview", "demo_onboarding", "initial", "{}", NOW()))
        row = c.execute("SELECT * FROM visitors WHERE guest_id=?", (guest_id,)).fetchone()
    return row


def adjust_tickets(c: sqlite3.Connection, guest_id: str, delta: int, reason: str, source_type: str, source_id: str, metadata: dict | None = None) -> bool:
    if delta == 0 or not source_id:
        return False
    get_visitor(c, guest_id)
    cur = c.execute("INSERT OR IGNORE INTO ticket_ledger(guest_id,delta,reason,source_type,source_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (guest_id, delta, reason[:180], source_type[:40], str(source_id)[:120], json.dumps(metadata or {}, ensure_ascii=False), NOW()))
    if cur.rowcount:
        # Negative balances are retained after a paid order is refunded; future earned tickets offset them.
        c.execute("UPDATE visitors SET tickets=tickets+? WHERE guest_id=?", (delta, guest_id))
        return True
    return False


def credit_tickets(c: sqlite3.Connection, guest_id: str, amount: int, reason: str, source_type: str, source_id: str, metadata: dict | None = None) -> bool:
    return adjust_tickets(c, guest_id, abs(int(amount)), reason, source_type, source_id, metadata) if amount > 0 else False


def referral_setting(c: sqlite3.Connection, key: str, default: int, low: int, high: int) -> int:
    row = c.execute("SELECT setting_value FROM site_settings WHERE setting_key=?", (key,)).fetchone()
    try:
        value = int(row[0]) if row else default
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def get_or_create_referral_code(c: sqlite3.Connection, guest_id: str) -> str:
    row = c.execute("SELECT code FROM referral_codes WHERE owner_guest_id=? AND active=1", (guest_id,)).fetchone()
    if row:
        return str(row[0])
    for _ in range(8):
        code = "SEA-" + secrets.token_hex(3).upper()
        try:
            c.execute("INSERT INTO referral_codes(code,owner_guest_id,created_at) VALUES(?,?,?)", (code, guest_id, NOW()))
            return code
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("could_not_allocate_referral_code")


def loyalty_tier(c: sqlite3.Connection, guest_id: str) -> dict:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=365)).isoformat(timespec="seconds")
    row = c.execute("SELECT COALESCE(SUM(MAX(0,subtotal_rub-discount_rub)),0) spend,COUNT(*) orders FROM orders WHERE guest_id=? AND status IN ('paid','preparing','ready','completed') AND created_at>=?", (guest_id, since)).fetchone()
    spend = int(row["spend"] or 0)
    sailor = referral_setting(c, "tier_sailor_rub", 5000, 0, 1000000)
    captain = max(sailor, referral_setting(c, "tier_captain_rub", 15000, 0, 1000000))
    admiral = max(captain, referral_setting(c, "tier_admiral_rub", 40000, 0, 1000000))
    tiers = [
        (0, "Гость гавани", "Базовый уровень клуба", "Участие в клубных активностях"),
        (sailor, "Моряк", "Первый уровень доверия", "Ранний доступ к сезонным привозам"),
        (captain, "Капитан", "Постоянный гость", "Приоритетные анонсы и закрытые предложения"),
        (admiral, "Адмирал", "Высший клубный статус", "Персональные предложения и приглашения на закрытые дегустации"),
    ]
    selected = tiers[0]
    next_tier = None
    for idx, tier in enumerate(tiers):
        if spend >= tier[0]:
            selected = tier
            next_tier = tiers[idx + 1] if idx + 1 < len(tiers) else None
    return {"name": selected[1], "description": selected[2], "benefit": selected[3], "spend_365d": spend, "orders_365d": int(row["orders"] or 0), "next_tier": next_tier[1] if next_tier else None, "to_next_tier": max(0, next_tier[0] - spend) if next_tier else 0}


def qualify_referral_for_paid_order(c: sqlite3.Connection, order: sqlite3.Row) -> dict:
    guest_id = str(order["guest_id"] or "")
    if not guest_id:
        return {"awarded": False}
    paid_count = c.execute("SELECT COUNT(*) FROM orders WHERE guest_id=? AND status IN ('paid','preparing','ready','completed')", (guest_id,)).fetchone()[0]
    if int(paid_count) != 1:
        return {"awarded": False, "reason": "not_first_paid_order"}
    attribution = c.execute("SELECT * FROM referral_attributions WHERE referred_guest_id=? AND status='pending'", (guest_id,)).fetchone()
    if not attribution:
        return {"awarded": False}
    min_order = referral_setting(c, "referral_min_order_rub", 1500, 0, 1000000)
    eligible = max(0, int(order["subtotal_rub"]) - int(order["discount_rub"]))
    if eligible < min_order:
        return {"awarded": False, "reason": "minimum_order_not_met"}
    inviter_reward = referral_setting(c, "referral_inviter_tickets", 10, 0, 100)
    friend_reward = referral_setting(c, "referral_friend_tickets", 5, 0, 100)
    source_id = str(order["id"])
    if inviter_reward:
        credit_tickets(c, attribution["referrer_guest_id"], inviter_reward, "Друг совершил первую подтверждённую покупку", "referral_inviter", source_id, {"referred_guest_id": guest_id})
    if friend_reward:
        credit_tickets(c, guest_id, friend_reward, "Бонус за первую покупку по приглашению", "referral_friend", source_id, {"referrer_guest_id": attribution["referrer_guest_id"]})
    c.execute("UPDATE referral_attributions SET status='rewarded',qualified_order_id=?,qualified_at=?,referrer_reward=?,friend_reward=? WHERE referred_guest_id=? AND status='pending'", (source_id, NOW(), inviter_reward, friend_reward, guest_id))
    return {"awarded": True, "referrer_tickets": inviter_reward, "friend_tickets": friend_reward}


def resolve_guest_id(value: Any = None) -> str:
    """Bind anonymous visitor IDs to this browser session; MAX identity wins."""
    max_guest = session.get("max_guest_id")
    if max_guest:
        return clean_guest_id(max_guest)
    candidate = clean_guest_id(value or request.args.get("guest_id", ""))
    bound = session.get("guest_id")
    if bound and not hmac.compare_digest(str(bound), candidate):
        abort(403, description="visitor_identity_mismatch")
    session["guest_id"] = candidate
    return candidate


def event(c: sqlite3.Connection, name: str, guest_id: str = "", metadata: dict | None = None):
    allowed = {"page_view", "product_view", "add_to_cart", "checkout_started", "order_created", "promo_applied", "wheel_spin", "contest_entry", "referral_attached", "referral_shared"}
    if name in allowed:
        c.execute("INSERT INTO events(event_name,guest_id,metadata_json,created_at) VALUES(?,?,?,?)",
                  (name, guest_id[:80], json.dumps(metadata or {}, ensure_ascii=False), NOW()))


def eligible_promotion(c: sqlite3.Connection, code: str, subtotal: int) -> sqlite3.Row | None:
    if not code:
        return None
    row = c.execute("SELECT * FROM promotions WHERE code=? AND active=1", (code.upper(),)).fetchone()
    if not row:
        return None
    today = TODAY()
    if row["starts_at"] and today < row["starts_at"]:
        return None
    if row["ends_at"] and today > row["ends_at"]:
        return None
    if row["max_uses"] and row["uses"] >= row["max_uses"]:
        return None
    if subtotal < row["min_order"]:
        return None
    return row


def discount_for(c: sqlite3.Connection, code: str, subtotal: int) -> tuple[int, str]:
    if not code:
        return 0, ""
    row = eligible_promotion(c, code, subtotal)
    if not row:
        # Return a clear, stable reason for the customer-facing quote.
        candidate = c.execute("SELECT * FROM promotions WHERE code=?", (code.upper(),)).fetchone()
        if not candidate or not candidate["active"]:
            return 0, "Промокод не найден или неактивен"
        today = TODAY()
        if candidate["starts_at"] and today < candidate["starts_at"]:
            return 0, "Промокод ещё не действует"
        if candidate["ends_at"] and today > candidate["ends_at"]:
            return 0, "Срок действия промокода закончился"
        if candidate["max_uses"] and candidate["uses"] >= candidate["max_uses"]:
            return 0, "Лимит использований промокода исчерпан"
        if subtotal < candidate["min_order"]:
            return 0, f"Минимальная сумма заказа для промокода — {candidate['min_order']} ₽"
        return 0, "Промокод недоступен"
    amount = round(subtotal * row["discount_value"] / 100) if row["discount_type"] == "percent" else row["discount_value"]
    return min(subtotal, max(0, amount)), row["title"]


def normalize_cart(c: sqlite3.Connection, items: Any) -> tuple[list[dict], int]:
    if not isinstance(items, list) or not items or len(items) > 30:
        abort(400, description="invalid_cart")
    normalized, subtotal = [], 0
    for item in items:
        if not isinstance(item, dict):
            abort(400, description="invalid_cart_item")
        pid, qty = str(item.get("id", "")), item.get("quantity")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1 or qty > 50:
            abort(400, description="invalid_quantity")
        product = c.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
        if not product or is_non_brand_product(dict(product)) or product["stock"] < qty:
            abort(409, description="item_unavailable")
        if product["price_on_request"]:
            abort(409, description="price_on_request")
        line = product["price"] * qty
        subtotal += line
        normalized.append({"id": product["id"], "title": product["title"], "quantity": qty,
                           "unit_price": product["price"], "line_total": line, "unit": product["unit"]})
    return normalized, subtotal


def validate_max_init_data(init_data: str) -> dict:
    try:
        return verify_max_init_data(init_data, MAX_BOT_TOKEN)
    except MaxInitDataError as exc:
        abort(exc.status, description=exc.code)


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    resp.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") or "/admin" in request.path else "public, max-age=300"
    resp.headers["Content-Security-Policy"] = "default-src 'self' https: data:; script-src 'self' https://st.max.ru; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' https: data:; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return resp



def notify_max_admin_order(order_id: str, total_rub: int, item_count: int, source_channel: str):
    """Optional preview notification; never includes customer contact data."""
    if not MAX_BOT_TOKEN or not MAX_ADMIN_USER_ID:
        return
    try:
        from max_client import send_message
        send_message(user_id=int(MAX_ADMIN_USER_ID), text=(
            f"🦞 РАКОВАРЪ · новая тестовая заявка {order_id}\n"
            f"Сумма: {total_rub} ₽ · позиций: {item_count} · канал: {source_channel}\n"
            "Это демонстрационный заказ: оплата не проводилась, персональные данные не сохранены."
        ))
    except Exception as exc:
        app.logger.warning("MAX order notification failed: %s", type(exc).__name__)

@app.get("/")
def storefront():
    with connect_db() as c:
        settings={r["setting_key"]:r["setting_value"] for r in c.execute("SELECT setting_key,setting_value FROM site_settings")}
    return render_template("storefront.html", demo_mode=DEMO_MODE, site_settings=settings)


@app.get("/admin/login")
def admin_login():
    if not ADMIN_PASSWORD_HASH:
        return render_template("admin_login.html", error="Администрирование не настроено: задайте ADMIN_PASSWORD_HASH в переменных окружения."), 503
    session["admin_csrf"] = secrets.token_urlsafe(32)
    return render_template("admin_login.html", error=None, csrf_token=session["admin_csrf"])


@app.post("/admin/login")
def admin_login_post():
    if not ADMIN_PASSWORD_HASH:
        abort(503)
    if not csrf_valid():
        abort(400)
    ip_key = request.remote_addr or "unknown"
    attempts, locked_until = _LOGIN_FAILURES.get(ip_key, (0, 0.0))
    if locked_until > time.monotonic():
        return render_template("admin_login.html", error="Слишком много попыток. Попробуйте позже.", csrf_token=session.get("admin_csrf", "")), 429
    password = request.form.get("password", "")
    if check_password_hash(ADMIN_PASSWORD_HASH, password):
        _LOGIN_FAILURES.pop(ip_key, None)
        session.clear()
        session["admin"] = True
        session["admin_csrf"] = secrets.token_urlsafe(32)
        session.permanent = True
        return redirect(url_for("admin_panel"))
    attempts += 1
    _LOGIN_FAILURES[ip_key] = (attempts, time.monotonic() + 900 if attempts >= 5 else 0.0)
    session["admin_csrf"] = secrets.token_urlsafe(32)
    return render_template("admin_login.html", error="Неверный пароль", csrf_token=session["admin_csrf"]), 401


@app.get("/admin")
@admin_required
def admin_panel():
    return render_template("admin.html", csrf_token=session.get("admin_csrf", ""), demo_mode=DEMO_MODE)


@app.post("/admin/logout")
@admin_required
def admin_logout():
    require_csrf()
    session.clear()
    return redirect(url_for("storefront"))


@app.post("/api/max/auth")
def max_auth():
    if rate_limited("max_auth", 30):
        return jsonify(error="rate_limited"), 429
    data = json_body()
    verified = validate_max_init_data(data.get("init_data", ""))
    guest_id = f"max_{verified['user_id']}"
    session.clear()
    session.permanent = True
    session["max_guest_id"] = guest_id
    session["max_user_id"] = verified["user_id"]
    session["max_auth_date"] = verified["auth_date"]
    return jsonify(status="authenticated", guest_id=guest_id, user={"id":verified["user_id"],"first_name":verified["user"].get("first_name","")}, start_param=verified.get("start_param", ""), csrf_token=csrf_token())


@app.post("/api/max/webhook")
def max_webhook():
    """Receive authenticated MAX bot events through the production webhook."""
    if not MAX_WEBHOOK_SECRET:
        return jsonify(error="max_webhook_not_configured"), 503
    supplied_secret = request.headers.get("X-Max-Bot-Api-Secret", "")
    if not hmac.compare_digest(supplied_secret, MAX_WEBHOOK_SECRET):
        return jsonify(error="unauthorized"), 401
    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return jsonify(error="invalid_update"), 400

    fingerprint = hashlib.sha256(
        json.dumps(update, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    with connect_db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS max_webhook_events (
                event_hash TEXT PRIMARY KEY,
                received_at TEXT NOT NULL,
                processed_at TEXT
            )"""
        )
        inserted = c.execute(
            "INSERT OR IGNORE INTO max_webhook_events(event_hash, received_at) VALUES(?, ?)",
            (fingerprint, NOW()),
        )
        if inserted.rowcount == 0:
            return jsonify(status="duplicate"), 200

    try:
        # Import lazily to avoid an app <-> bot import cycle during startup.
        from max_bot import handle_update
        handle_update(update, MAX_BOT_USERNAME)
    except Exception:
        with connect_db() as c:
            c.execute("DELETE FROM max_webhook_events WHERE event_hash=?", (fingerprint,))
        app.logger.exception("MAX webhook event processing failed")
        return jsonify(error="event_processing_failed"), 500

    with connect_db() as c:
        c.execute(
            "UPDATE max_webhook_events SET processed_at=? WHERE event_hash=?",
            (NOW(), fingerprint),
        )
    return jsonify(status="ok"), 200


@app.get("/api/bootstrap")
def bootstrap():
    guest_id = resolve_guest_id(request.args.get("guest_id", "")) if request.args.get("guest_id") or session.get("max_guest_id") else ""
    with connect_db() as c:
        products = public_catalog_products(c)
        promos = [dict(r) for r in c.execute("SELECT code,title,description,discount_type,discount_value,min_order FROM promotions WHERE active=1")]
        contests = [dict(r) for r in c.execute("SELECT id,title,description,prize_title,starts_at,ends_at,status,rules FROM contests WHERE status='active'")]
        prizes = [dict(r) for r in c.execute("SELECT id,title,kind,description,stock,partner FROM prizes WHERE active=1 AND stock>0")]
        settings = {r["setting_key"]: r["setting_value"] for r in c.execute("SELECT setting_key,setting_value FROM site_settings")}
        visitor = dict(get_visitor(c, clean_guest_id(guest_id))) if guest_id else None
        referral_code = get_or_create_referral_code(c, clean_guest_id(guest_id)) if guest_id else ""
        tier = loyalty_tier(c, clean_guest_id(guest_id)) if guest_id else None
        return jsonify(demo_mode=DEMO_MODE, csrf_token=csrf_token(), products=products, promotions=promos,
                       contests=contests, prizes=prizes, settings=settings, visitor=visitor, referral_code=referral_code, loyalty_tier=tier,
                       loyalty_rules={"rub_per_ticket":LOYALTY_RUB_PER_TICKET,"purchase_credit_on":"paid_status_only"},
                       max_bot_configured=bool(MAX_BOT_TOKEN),
                       notice="Предварительный каталог. Цены, наличие, условия и права на фотографии требуют подтверждения компании.")


@app.get("/api/referrals/profile")
def referral_profile():
    guest_id = resolve_guest_id(request.args.get("guest_id"))
    with connect_db() as c:
        code = get_or_create_referral_code(c, guest_id)
        stats = c.execute("SELECT COUNT(*) total,SUM(CASE WHEN status='rewarded' THEN 1 ELSE 0 END) qualified,SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending FROM referral_attributions WHERE referrer_guest_id=?", (guest_id,)).fetchone()
        visitor = get_visitor(c, guest_id)
        return jsonify(code=code, total=int(stats["total"] or 0), qualified=int(stats["qualified"] or 0), pending=int(stats["pending"] or 0),
                       tickets=int(visitor["tickets"]), tier=loyalty_tier(c, guest_id),
                       rules={"minimum_order_rub":referral_setting(c,"referral_min_order_rub",1500,0,1000000),
                              "referrer_tickets":referral_setting(c,"referral_inviter_tickets",10,0,100),
                              "friend_tickets":referral_setting(c,"referral_friend_tickets",5,0,100)})


@app.post("/api/referrals/attach")
def referral_attach():
    if rate_limited("referral_attach", 20):
        return jsonify(error="rate_limited"), 429
    require_csrf()
    data = json_body()
    code = str(data.get("code", "")).strip().upper()[:32]
    guest_id = resolve_guest_id(data.get("guest_id"))
    if not code:
        return jsonify(error="invalid_referral_code"), 400
    with connect_db() as c:
        existing = c.execute("SELECT 1 FROM referral_attributions WHERE referred_guest_id=?", (guest_id,)).fetchone()
        if existing:
            return jsonify(error="referral_already_attached", message="Приглашение уже закреплено за этим аккаунтом."), 409
        prior_orders = c.execute("SELECT 1 FROM orders WHERE guest_id=? AND status IN ('paid','preparing','ready','completed') LIMIT 1", (guest_id,)).fetchone()
        if prior_orders:
            return jsonify(error="referral_not_new_customer", message="Реферальный код можно применить до первой оплаченной покупки."), 409
        ref = c.execute("SELECT owner_guest_id FROM referral_codes WHERE code=? AND active=1", (code,)).fetchone()
        if not ref:
            return jsonify(error="referral_code_not_found", message="Такой код приглашения не найден."), 404
        if hmac.compare_digest(str(ref["owner_guest_id"]), guest_id):
            return jsonify(error="self_referral_not_allowed", message="Нельзя применить собственный код."), 400
        try:
            c.execute("INSERT INTO referral_attributions(referred_guest_id,referrer_guest_id,code,status,created_at) VALUES(?,?,?,'pending',?)", (guest_id, ref["owner_guest_id"], code, NOW()))
        except sqlite3.IntegrityError:
            return jsonify(error="referral_already_attached"), 409
        event(c, "referral_attached", guest_id, {"code":code})
        audit(c, "attach_referral", "referral", guest_id, {"code":code}) if session.get("admin") else None
        return jsonify(status="attached", message="Приглашение закреплено. Бонусы начислятся после первой подтверждённой покупки друга и проверки условий."), 201


@app.get("/api/products")
def products():
    with connect_db() as c:
        return jsonify(public_catalog_products(c))


@app.post("/api/events")
def track_event():
    if rate_limited("events", 120):
        return jsonify(error="rate_limited"), 429
    data = json_body()
    guest_id = resolve_guest_id(data.get("guest_id")) if data.get("guest_id") or session.get("max_guest_id") else ""
    with connect_db() as c:
        event(c, str(data.get("event", "")), guest_id, data.get("metadata") if isinstance(data.get("metadata"), dict) else {})
    return jsonify(status="accepted")


@app.post("/api/checkout/quote")
def checkout_quote():
    data = json_body()
    with connect_db() as c:
        items, subtotal = normalize_cart(c, data.get("items"))
        promo_code = str(data.get("promo_code", "")).strip().upper()
        discount, promo_result = discount_for(c, promo_code, subtotal)
        promo_valid = bool(eligible_promotion(c, promo_code, subtotal))
        mode = data.get("delivery_mode", "delivery")
        if mode not in {"delivery", "pickup"}:
            abort(400, description="invalid_delivery_mode")
        if mode == "delivery" and subtotal < PREVIEW_DELIVERY_MIN_RUB:
            abort(400, description="delivery_min_order")
        delivery = 0 if mode == "pickup" else PREVIEW_DELIVERY_RUB
        return jsonify(items=items, subtotal_rub=subtotal, discount_rub=discount, delivery_rub=delivery,
                       total_rub=max(0, subtotal-discount+delivery), promo_message=promo_result, promo_valid=promo_valid)


@app.post("/api/orders")
def create_order():
    if rate_limited("orders", 10):
        return jsonify(error="rate_limited"), 429
    if not DEMO_MODE:
        return jsonify(error="checkout_not_configured", message="Реальные заказы отключены до подключения БД, оплаты, уведомлений и юридических документов."), 503
    require_csrf()
    data = json_body()
    guest_id = resolve_guest_id(data.get("guest_id"))
    source_channel = "max" if session.get("max_guest_id") else "web"
    # Validate input, but intentionally discard all personal contact data in demo mode.
    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    if len(name) < 2 or len(name) > 80 or len(phone) < 6 or len(phone) > 32 or data.get("consent") is not True:
        return jsonify(error="invalid_checkout", message="Укажите имя, телефон и подтвердите согласие для демонстрации."), 400
    with connect_db() as c:
        items, subtotal = normalize_cart(c, data.get("items"))
        code = str(data.get("promo_code", "")).strip().upper()
        discount, promo_message = discount_for(c, code, subtotal)
        promo_row = eligible_promotion(c, code, subtotal)
        applied_code = code if promo_row else ""
        mode = data.get("delivery_mode", "delivery")
        if mode not in {"delivery", "pickup"}:
            abort(400)
        if mode == "delivery" and subtotal < PREVIEW_DELIVERY_MIN_RUB:
            return jsonify(error="delivery_min_order",message=f"Предварительный минимальный заказ для доставки — {PREVIEW_DELIVERY_MIN_RUB} ₽. Условия требуется подтвердить у менеджера."),400
        delivery = 0 if mode == "pickup" else PREVIEW_DELIVERY_RUB
        total = max(0, subtotal-discount+delivery)
        order_id = "DEMO-" + secrets.token_hex(4).upper()
        c.execute("INSERT INTO orders(id,created_at,customer_label,contact_label,delivery_mode,address_label,items_json,subtotal_rub,discount_rub,delivery_rub,total_rub,promo_code,status,is_demo,guest_id,source_channel) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                  (order_id, NOW(), "ДЕМО-ПОКУПАТЕЛЬ", "НЕ СОХРАНЕНО", mode, "НЕ СОХРАНЕНО",
                   json.dumps(items, ensure_ascii=False), subtotal, discount, delivery, total, applied_code, "demo_received", guest_id, source_channel))
        if promo_row:
            c.execute("UPDATE promotions SET uses=uses+1 WHERE code=?", (code,))
            event(c, "promo_applied", guest_id, {"code":code,"ticket_reward":int(promo_row["ticket_reward"] or 0)})
        event(c, "order_created", guest_id, {"order_id": order_id, "total_rub": total})
    notify_max_admin_order(order_id, total, len(items), source_channel)
    return jsonify(status="demo_order_created", order_id=order_id, total_rub=total,
                   message="Тестовый заказ сохранён в демонстрационной админке. Компания его не получит; контакты не сохранены."), 201


@app.get("/api/game/profile")
def game_profile():
    guest_id = resolve_guest_id(request.args.get("guest_id"))
    with connect_db() as c:
        return jsonify(dict(get_visitor(c, guest_id)))


@app.post("/api/game/daily-ticket")
def daily_ticket():
    return jsonify(error="ticket_rule_changed", message="Билеты начисляются за подтверждённые покупки и специальные акции, а не ежедневно."), 410


@app.post("/api/game/spin")
def game_spin():
    if rate_limited("spins", 20):
        return jsonify(error="rate_limited"), 429
    if not DEMO_MODE:
        return jsonify(error="game_not_configured"), 503
    require_csrf()
    guest_id = resolve_guest_id(json_body().get("guest_id"))
    with connect_db() as c:
        c.execute("BEGIN IMMEDIATE")
        visitor = get_visitor(c, guest_id)
        if visitor["tickets"] < 1:
            return jsonify(error="no_tickets", message="Нет клубных билетов. Их можно получить за подтверждённые покупки и участие в акциях."), 409
        candidates = c.execute("SELECT * FROM prizes WHERE active=1 AND stock>0 AND weight>0").fetchall()
        if not candidates:
            return jsonify(error="no_prizes"), 409
        total_weight = sum(int(p["weight"]) for p in candidates)
        pick = secrets.randbelow(total_weight)
        chosen = candidates[-1]
        for prize in candidates:
            pick -= int(prize["weight"])
            if pick < 0:
                chosen = prize
                break
        c.execute("UPDATE visitors SET tickets=tickets-1 WHERE guest_id=?", (guest_id,))
        if chosen["stock"] < 9999:
            c.execute("UPDATE prizes SET stock=stock-1 WHERE id=? AND stock>0", (chosen["id"],))
        if chosen["kind"] == "points":
            c.execute("UPDATE visitors SET points=points+50 WHERE guest_id=?", (guest_id,))
        redemption_code = ""
        if chosen["kind"] in {"coupon", "gift", "delivery"}:
            redemption_code = "RK-" + secrets.token_hex(4).upper()
        if chosen["kind"] == "coupon" and int(chosen["reward_value"] or 0) > 0:
            c.execute("INSERT INTO promotions(code,title,description,discount_type,discount_value,min_order,max_uses,active) VALUES(?,?,?,?,?,?,?,1)",
                      (redemption_code, chosen["title"], "Персональный демонстрационный призовой код", "percent", int(chosen["reward_value"]), 0, 1))
        spin_cur = c.execute("INSERT INTO spins(guest_id,prize_id,prize_title,redemption_code,created_at) VALUES(?,?,?,?,?)",
                  (guest_id, chosen["id"], chosen["title"], redemption_code, NOW()))
        c.execute("INSERT OR IGNORE INTO ticket_ledger(guest_id,delta,reason,source_type,source_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                  (guest_id, -1, "Использован билет в игровой зоне", "spin", str(spin_cur.lastrowid), json.dumps({"prize_id":chosen["id"]}), NOW()))
        event(c, "wheel_spin", guest_id, {"prize_id": chosen["id"]})
        remaining = c.execute("SELECT tickets FROM visitors WHERE guest_id=?", (guest_id,)).fetchone()[0]
        points = c.execute("SELECT points FROM visitors WHERE guest_id=?", (guest_id,)).fetchone()[0]
        return jsonify(status="won", prize={"id":chosen["id"],"title":chosen["title"],"description":chosen["description"],"partner":chosen["partner"]},
                       redemption_code=redemption_code, tickets=remaining, points=points,
                       message="Демонстрационный розыгрыш: приз не является обещанием реальной выдачи.")


@app.get("/api/game/history")
def game_history():
    guest_id = resolve_guest_id(request.args.get("guest_id"))
    with connect_db() as c:
        rows = c.execute("SELECT prize_title,redemption_code,created_at,status FROM spins WHERE guest_id=? ORDER BY id DESC LIMIT 20", (guest_id,)).fetchall()
        return jsonify([dict(r) for r in rows])


@app.post("/api/contests/<contest_id>/entries")
def contest_entry(contest_id):
    if rate_limited("contest_entries", 10):
        return jsonify(error="rate_limited"), 429
    if not DEMO_MODE:
        return jsonify(error="contest_not_configured"), 503
    require_csrf()
    data = json_body()
    guest_id = resolve_guest_id(data.get("guest_id"))
    alias = str(data.get("alias", "")).strip()[:40]
    answer = str(data.get("answer", "")).strip()[:500]
    if len(alias) < 2 or len(answer) < 5:
        return jsonify(error="invalid_entry", message="Укажите имя участника и короткий ответ."), 400
    with connect_db() as c:
        contest = c.execute("SELECT * FROM contests WHERE id=? AND status='active'", (contest_id,)).fetchone()
        if not contest or TODAY() < contest["starts_at"] or TODAY() > contest["ends_at"]:
            return jsonify(error="contest_closed"), 409
        try:
            c.execute("INSERT INTO contest_entries(contest_id,guest_id,alias,answer,created_at) VALUES(?,?,?,?,?)",
                      (contest_id, guest_id, alias, answer, NOW()))
        except sqlite3.IntegrityError:
            return jsonify(error="already_entered", message="Вы уже участвуете в этом конкурсе."), 409
        entry_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        ticket_reward = int(contest["ticket_reward"] or 0)
        if ticket_reward:
            credit_tickets(c, guest_id, ticket_reward, f"Участие в акции: {contest['title']}", "contest_entry", f"{contest_id}:{entry_id}", {"contest_id":contest_id})
        event(c, "contest_entry", guest_id, {"contest_id": contest_id, "tickets_awarded":ticket_reward})
        count = c.execute("SELECT COUNT(*) FROM contest_entries WHERE contest_id=?", (contest_id,)).fetchone()[0]
        balance = c.execute("SELECT tickets FROM visitors WHERE guest_id=?", (guest_id,)).fetchone()[0]
        return jsonify(status="entered", entries=count, tickets_awarded=ticket_reward, tickets=balance, message="Тестовая заявка сохранена в демо-системе."), 201


@app.get("/api/contests/<contest_id>/entries/count")
def contest_count(contest_id):
    with connect_db() as c:
        count = c.execute("SELECT COUNT(*) FROM contest_entries WHERE contest_id=?", (contest_id,)).fetchone()[0]
        return jsonify(entries=count)


# ------------------------------- ADMIN API ---------------------------------
@app.get("/api/admin/dashboard")
@admin_required
def admin_dashboard():
    with connect_db() as c:
        orders = c.execute("SELECT COUNT(*) n,COALESCE(SUM(total_rub),0) revenue FROM orders").fetchone()
        return jsonify(orders=int(orders["n"]), demo_revenue=int(orders["revenue"]),
          products=c.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0],
          low_stock=c.execute("SELECT COUNT(*) FROM products WHERE active=1 AND stock<=5").fetchone()[0],
          visitors=c.execute("SELECT COUNT(*) FROM visitors").fetchone()[0],
          spins=c.execute("SELECT COUNT(*) FROM spins").fetchone()[0],
          contest_entries=c.execute("SELECT COUNT(*) FROM contest_entries").fetchone()[0],
          referrals=c.execute("SELECT COUNT(*) FROM referral_attributions").fetchone()[0],
          qualified_referrals=c.execute("SELECT COUNT(*) FROM referral_attributions WHERE status='rewarded'").fetchone()[0],
          active_promotions=c.execute("SELECT COUNT(*) FROM promotions WHERE active=1").fetchone()[0],
          content_drafts=c.execute("SELECT COUNT(*) FROM content_posts WHERE status IN ('draft','planned')").fetchone()[0],
          recent_orders=[dict(r) for r in c.execute("SELECT id,created_at,total_rub,status,items_json FROM orders ORDER BY created_at DESC LIMIT 8")])


@app.get("/api/admin/orders")
@admin_required
def admin_orders():
    with connect_db() as c:
        return jsonify([dict(r) for r in c.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 200")])


@app.patch("/api/admin/orders/<order_id>")
@admin_required
def admin_order_update(order_id):
    require_csrf()
    status = str(json_body().get("status", ""))
    allowed = {"demo_received", "confirmed", "paid", "preparing", "ready", "completed", "cancelled"}
    if status not in allowed:
        abort(400)
    with connect_db() as c:
        order = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            abort(404)
        previous = order["status"]
        if status == "paid":
            reversed_before = c.execute("SELECT 1 FROM ticket_ledger WHERE guest_id=? AND source_type IN ('purchase_reversal','purchase_promo_reversal') AND source_id=?",(order["guest_id"],order_id)).fetchone() if order["guest_id"] else None
            if previous == "cancelled" or reversed_before:
                return jsonify(error="cancelled_order_cannot_be_reopened",message="Создайте новый заказ вместо повторного открытия отменённого."),409
        c.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        awarded = 0
        if status == "paid" and previous != "paid" and order["guest_id"]:
            eligible_spend = max(0, int(order["subtotal_rub"]) - int(order["discount_rub"]))
            loyalty_rate = get_loyalty_rate(c)
            purchase_tickets = eligible_spend // loyalty_rate
            if purchase_tickets:
                if credit_tickets(c, order["guest_id"], purchase_tickets,
                                  f"Покупка {order_id}", "purchase", order_id,
                                  {"eligible_spend_rub":eligible_spend,"rate_rub":loyalty_rate}):
                    awarded += purchase_tickets
            if order["promo_code"]:
                promo = c.execute("SELECT ticket_reward FROM promotions WHERE code=?", (order["promo_code"],)).fetchone()
                if promo and int(promo["ticket_reward"] or 0):
                    reward = int(promo["ticket_reward"])
                    if credit_tickets(c, order["guest_id"], reward, f"Промоакция {order['promo_code']}",
                                      "purchase_promo", order_id, {"code":order["promo_code"]}):
                        awarded += reward
            referral_result = qualify_referral_for_paid_order(c, order)
            if referral_result.get("awarded"):
                awarded += int(referral_result.get("friend_tickets", 0))
        reversed_tickets = 0
        if status == "cancelled" and previous == "paid" and order["guest_id"]:
            # Reverse the exact ledger amounts originally granted, not today's loyalty/promo settings.
            purchase_ledger = c.execute("SELECT delta FROM ticket_ledger WHERE guest_id=? AND source_type='purchase' AND source_id=?",
                                        (order["guest_id"],order_id)).fetchone()
            base_award = int(purchase_ledger["delta"]) if purchase_ledger else 0
            if base_award and adjust_tickets(c, order["guest_id"], -base_award,
                    f"Отмена оплаченного заказа {order_id}", "purchase_reversal", order_id,
                    {"reversed_source":"purchase"}):
                reversed_tickets += base_award
            promo_ledger = c.execute("SELECT delta FROM ticket_ledger WHERE guest_id=? AND source_type='purchase_promo' AND source_id=?",
                                     (order["guest_id"],order_id)).fetchone()
            promo_award = int(promo_ledger["delta"]) if promo_ledger else 0
            if promo_award and adjust_tickets(c, order["guest_id"], -promo_award,
                    f"Отмена промо-билета заказа {order_id}", "purchase_promo_reversal", order_id,
                    {"code":order["promo_code"]}):
                reversed_tickets += promo_award
            referral = c.execute("SELECT * FROM referral_attributions WHERE referred_guest_id=? AND qualified_order_id=? AND status='rewarded'", (order["guest_id"], order_id)).fetchone()
            if referral:
                for beneficiary, source_type, reward, reason in [
                    (referral["referrer_guest_id"], "referral_inviter_reversal", int(referral["referrer_reward"]), "Сторнирование реферального бонуса: заказ друга отменён"),
                    (order["guest_id"], "referral_friend_reversal", int(referral["friend_reward"]), "Сторнирование бонуса приглашённого: заказ отменён"),
                ]:
                    if reward and adjust_tickets(c, beneficiary, -reward, reason, source_type, order_id, {"reversed_order":order_id}):
                        reversed_tickets += reward
                c.execute("UPDATE referral_attributions SET status='reversed' WHERE referred_guest_id=?", (order["guest_id"],))
        audit(c, "update_status", "order", order_id, {"status":status,"tickets_awarded":awarded,"tickets_reversed":reversed_tickets})
    return jsonify(status="updated", tickets_awarded=awarded, tickets_reversed=reversed_tickets)


@app.get("/api/admin/products")
@admin_required
def admin_products():
    with connect_db() as c:
        return jsonify([dict(r) for r in c.execute("SELECT * FROM products ORDER BY created_at DESC")])


@app.post("/api/admin/products")
@admin_required
def admin_product_create():
    require_csrf()
    d = json_body()
    pid = "p-" + secrets.token_hex(5)
    title, category = str(d.get("title", "")).strip()[:100], str(d.get("category", "")).strip()[:40]
    try:
        price, stock = int(d.get("price")), int(d.get("stock", 0))
    except (TypeError, ValueError):
        abort(400)
    if len(title)<2 or not category or price<0 or stock<0 or stock>100000: abort(400)
    image = str(d.get("image", "opt_hero.svg"))
    image_url = str(d.get("image_url", "")).strip()
    source_url = str(d.get("source_url", "")).strip()
    price_on_request = 1 if d.get("price_on_request") in (1, True, "1", "true", "on") else 0
    if image not in {"opt_hero.svg","opt_crayfish.svg","opt_prawns.svg","opt_platter.svg","opt_bouquet.svg"}: abort(400)
    if image_url and not image_url.startswith("https://"): abort(400)
    if source_url and not source_url.startswith("https://"): abort(400)
    if is_non_brand_product({"title":title,"category":category,"description":d.get("description",""),"image":image,"image_url":image_url}):
        abort(400, description="unsupported_catalog_item")
    with connect_db() as c:
        c.execute("INSERT INTO products(id,title,category,price,unit,stock,description,image,badge,created_at,image_url,source_url,price_verified,stock_confirmed,weight_label,price_on_request) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (pid,title,category,price,str(d.get("unit","за шт."))[:20],stock,str(d.get("description",""))[:500],image,str(d.get("badge",""))[:40],NOW(),image_url,source_url,0,0,str(d.get("weight_label",""))[:40],price_on_request))
        audit(c,"create","product",pid,{"title":title})
    return jsonify(id=pid),201


@app.patch("/api/admin/products/<product_id>")
@admin_required
def admin_product_update(product_id):
    require_csrf()
    d=json_body(); fields={}
    for key in ("title","category","unit","description","badge"):
        if key in d: fields[key]=str(d[key])[:500]
    for key in ("price","stock","active","price_verified","stock_confirmed","price_on_request"):
        if key in d:
            try: fields[key]=int(d[key])
            except (TypeError,ValueError): abort(400)
    if "title" in fields and len(fields["title"].strip())<2: abort(400)
    if "category" in fields and len(fields["category"].strip())<2: abort(400)
    if "unit" in fields and not fields["unit"].strip(): abort(400)
    if "price" in fields and fields["price"]<0: abort(400)
    if "stock" in fields and not 0<=fields["stock"]<=100000: abort(400)
    if "active" in fields and fields["active"] not in (0,1): abort(400)
    for flag in ("price_verified","stock_confirmed","price_on_request"):
        if flag in fields and fields[flag] not in (0,1): abort(400)
    for key in ("image_url","source_url","weight_label"):
        if key in d:
            value = str(d[key]).strip()
            if key in {"image_url","source_url"} and value and not value.startswith("https://"): abort(400)
            fields[key] = value[:500]
    if "image" in d:
        if d["image"] not in {"opt_hero.svg","opt_crayfish.svg","opt_prawns.svg","opt_platter.svg","opt_bouquet.svg"}: abort(400)
        fields["image"]=d["image"]
    if not fields: abort(400)
    with connect_db() as c:
        existing = c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not existing: abort(404)
        candidate = dict(existing)
        candidate.update(fields)
        if int(candidate.get("active", 1)) and is_non_brand_product(candidate):
            abort(400, description="unsupported_catalog_item")
        cur=c.execute("UPDATE products SET "+",".join(f"{k}=?" for k in fields)+" WHERE id=?",(*fields.values(),product_id))
        if not cur.rowcount: abort(404)
        audit(c,"update","product",product_id,fields)
    return jsonify(status="updated")


@app.get("/api/admin/promotions")
@admin_required
def admin_promotions():
    with connect_db() as c: return jsonify([dict(r) for r in c.execute("SELECT * FROM promotions ORDER BY code")])


@app.post("/api/admin/promotions")
@admin_required
def admin_promotion_create():
    require_csrf(); d=json_body(); code=str(d.get("code"," ")).strip().upper()
    typ=str(d.get("discount_type","percent"))
    try:
        value=int(d.get("discount_value",0)); min_order=int(d.get("min_order",0)); max_uses=int(d.get("max_uses",0)); ticket_reward=int(d.get("ticket_reward",0))
    except (TypeError,ValueError): abort(400)
    if not 3<=len(code)<=24 or not code.replace("-","").isalnum() or typ not in {"percent","fixed"} or value<0 or (value==0 and ticket_reward==0) or (typ=="percent" and value>90) or min_order<0 or max_uses<0 or not 0<=ticket_reward<=20: abort(400)
    with connect_db() as c:
        try: c.execute("INSERT INTO promotions(code,title,description,discount_type,discount_value,min_order,max_uses,active,starts_at,ends_at,ticket_reward) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
          (code,str(d.get("title",code))[:100],str(d.get("description",""))[:500],typ,value,min_order,max_uses,1,str(d.get("starts_at","")),str(d.get("ends_at","")),ticket_reward))
        except sqlite3.IntegrityError: return jsonify(error="code_exists"),409
        audit(c,"create","promotion",code)
    return jsonify(code=code),201


@app.patch("/api/admin/promotions/<code>")
@admin_required
def admin_promotion_update(code):
    require_csrf(); d=json_body()
    fields={}
    if "active" in d:
        try: fields["active"]=int(d["active"])
        except (TypeError,ValueError): abort(400)
        if fields["active"] not in (0,1): abort(400)
    if "ticket_reward" in d:
        try: fields["ticket_reward"]=int(d["ticket_reward"])
        except (TypeError,ValueError): abort(400)
        if not 0<=fields["ticket_reward"]<=20: abort(400)
    if not fields: abort(400)
    with connect_db() as c:
        cur=c.execute("UPDATE promotions SET "+",".join(f"{k}=?" for k in fields)+" WHERE code=?",(*fields.values(),code.upper()))
        if not cur.rowcount: abort(404)
        audit(c,"update","promotion",code,fields)
    return jsonify(status="updated")


@app.get("/api/admin/prizes")
@admin_required
def admin_prizes():
    with connect_db() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM prizes ORDER BY title")]
        total=sum(int(r["weight"]) for r in rows if r["active"] and r["stock"]>0)
        for row in rows:
            row["probability_pct"]=round(100*int(row["weight"])/total,1) if row["active"] and row["stock"]>0 and total else 0
        return jsonify(rows)


@app.post("/api/admin/prizes")
@admin_required
def admin_prize_create():
    require_csrf(); d=json_body(); pid="prize-"+secrets.token_hex(4)
    title=str(d.get("title"," ")).strip()[:100]
    try:
        stock=int(d.get("stock",0)); weight=int(d.get("weight",1)); reward_value=int(d.get("reward_value",0))
    except (TypeError,ValueError): abort(400)
    kind=str(d.get("kind","gift"))
    if len(title)<2 or stock<0 or weight<1 or weight>1000 or reward_value<0 or reward_value>90 or kind not in {"gift","coupon","points","delivery"}: abort(400)
    with connect_db() as c:
        c.execute("INSERT INTO prizes(id,title,kind,description,stock,weight,partner,reward_value,active) VALUES(?,?,?,?,?,?,?,?,1)",
          (pid,title,kind,str(d.get("description",""))[:500],stock,weight,str(d.get("partner","РАКОВАРЪ"))[:80],reward_value))
        audit(c,"create","prize",pid)
    return jsonify(id=pid),201


@app.patch("/api/admin/prizes/<prize_id>")
@admin_required
def admin_prize_update(prize_id):
    require_csrf(); d=json_body(); fields={}
    for key in ("title","description","partner","kind"):
        if key in d: fields[key]=str(d[key])[:500]
    for key in ("stock","weight","active","reward_value"):
        if key in d:
            try: fields[key]=int(d[key])
            except (TypeError,ValueError): abort(400)
    if not fields: abort(400)
    if fields.get("kind", "gift") not in {"gift","coupon","points","delivery"}: abort(400)
    if "title" in fields and len(fields["title"].strip())<2: abort(400)
    if fields.get("stock",0)<0 or fields.get("stock",0)>100000 or fields.get("weight",1)<1 or fields.get("weight",1)>1000 or fields.get("active",1) not in (0,1) or fields.get("reward_value",0)<0 or fields.get("reward_value",0)>90: abort(400)
    with connect_db() as c:
        cur=c.execute("UPDATE prizes SET "+",".join(f"{k}=?" for k in fields)+" WHERE id=?",(*fields.values(),prize_id))
        if not cur.rowcount: abort(404)
        audit(c,"update","prize",prize_id,fields)
    return jsonify(status="updated")


@app.get("/api/admin/spins")
@admin_required
def admin_spins():
    with connect_db() as c:
        return jsonify([dict(r) for r in c.execute("SELECT id,guest_id,prize_title,redemption_code,created_at,status FROM spins ORDER BY id DESC LIMIT 100")])


@app.patch("/api/admin/spins/<int:spin_id>")
@admin_required
def admin_spin_update(spin_id):
    require_csrf()
    status = str(json_body().get("status", ""))
    if status not in {"issued", "expired", "unclaimed"}: abort(400)
    with connect_db() as c:
        cur = c.execute("UPDATE spins SET status=? WHERE id=?", (status, spin_id))
        if not cur.rowcount: abort(404)
        audit(c, "update_prize_status", "spin", spin_id, {"status":status})
    return jsonify(status="updated")


@app.get("/api/admin/contests")
@admin_required
def admin_contests():
    with connect_db() as c:
        rows=[]
        for r in c.execute("SELECT * FROM contests ORDER BY starts_at DESC"):
            item=dict(r); item["entries"]=c.execute("SELECT COUNT(*) FROM contest_entries WHERE contest_id=?",(r["id"],)).fetchone()[0]
            item["winners"]=[dict(w) for w in c.execute("SELECT alias,answer,created_at FROM contest_winners WHERE contest_id=? ORDER BY id",(r["id"],))]
            rows.append(item)
        return jsonify(rows)


@app.post("/api/admin/contests")
@admin_required
def admin_contest_create():
    require_csrf(); d=json_body(); cid="contest-"+secrets.token_hex(4)
    title=str(d.get("title"," ")).strip()[:120]; prize=str(d.get("prize_title"," ")).strip()[:120]
    start=str(d.get("starts_at",TODAY())); end=str(d.get("ends_at",TODAY()))
    try:
        dt.date.fromisoformat(start); dt.date.fromisoformat(end); ticket_reward=int(d.get("ticket_reward",0))
    except (ValueError,TypeError): abort(400)
    if len(title)<3 or len(prize)<2 or end<start or not 0<=ticket_reward<=20: abort(400)
    with connect_db() as c:
        c.execute("INSERT INTO contests(id,title,description,prize_title,starts_at,ends_at,status,max_entries,rules,ticket_reward) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (cid,title,str(d.get("description",""))[:1000],prize,start,end,"active",1,str(d.get("rules",""))[:2000],ticket_reward))
        audit(c,"create","contest",cid)
    return jsonify(id=cid),201



@app.patch("/api/admin/contests/<contest_id>")
@admin_required
def admin_contest_update(contest_id):
    require_csrf(); d=json_body(); fields={}
    with connect_db() as c:
        current=c.execute("SELECT * FROM contests WHERE id=?",(contest_id,)).fetchone()
        if not current: abort(404)
        if current["status"]=="drawn":
            return jsonify(error="contest_already_drawn",message="Проведённый розыгрыш нельзя редактировать."),409
        for key in ("title","description","prize_title","rules"):
            if key in d: fields[key]=str(d[key]).strip()[:2000]
        for key in ("starts_at","ends_at"):
            if key in d:
                value=str(d[key])
                try: dt.date.fromisoformat(value)
                except ValueError: abort(400)
                fields[key]=value
        if "ticket_reward" in d:
            try: fields["ticket_reward"]=int(d["ticket_reward"])
            except (TypeError,ValueError): abort(400)
            if not 0<=fields["ticket_reward"]<=20: abort(400)
        if "status" in d:
            status=str(d["status"])
            if status not in {"active","paused","closed"}: abort(400)
            fields["status"]=status
        title=fields.get("title",current["title"])
        prize=fields.get("prize_title",current["prize_title"])
        start=fields.get("starts_at",current["starts_at"])
        end=fields.get("ends_at",current["ends_at"])
        if len(title)<3 or len(prize)<2 or end<start: abort(400)
        if not fields: abort(400)
        c.execute("UPDATE contests SET "+",".join(f"{k}=?" for k in fields)+" WHERE id=?",(*fields.values(),contest_id))
        audit(c,"update","contest",contest_id,fields)
    return jsonify(status="updated")

@app.post("/api/admin/contests/<contest_id>/draw")
@admin_required
def admin_contest_draw(contest_id):
    require_csrf(); d=json_body()
    try: winners=max(1,min(int(d.get("winners",1)),10))
    except (TypeError,ValueError): abort(400)
    with connect_db() as c:
        contest=c.execute("SELECT * FROM contests WHERE id=?",(contest_id,)).fetchone()
        if not contest: abort(404)
        if contest["status"]!="active": return jsonify(error="contest_not_active"),409
        if TODAY() < contest["ends_at"]: return jsonify(error="contest_not_ended",message="Срок приёма заявок ещё не завершён."),409
        entries=c.execute("SELECT * FROM contest_entries WHERE contest_id=?",(contest_id,)).fetchall()
        if not entries: return jsonify(error="no_entries"),409
        selected=secrets.SystemRandom().sample(list(entries),min(winners,len(entries)))
        c.execute("UPDATE contests SET status='drawn' WHERE id=?",(contest_id,))
        for row in selected:
            c.execute("INSERT INTO contest_winners(contest_id,entry_id,alias,answer,created_at) VALUES(?,?,?,?,?)",
                      (contest_id,row["id"],row["alias"],row["answer"],NOW()))
            c.execute("INSERT INTO audit_log(actor,action,entity,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?)",
              ("admin","draw_winner","contest",contest_id,json.dumps({"alias":row["alias"],"entry_id":row["id"]},ensure_ascii=False),NOW()))
        return jsonify(status="drawn",winners=[{"alias":r["alias"],"answer":r["answer"]} for r in selected],
                       note="Результат демо-розыгрыша. Перед реальным объявлением проверьте правила и личность участника.")


@app.get("/api/admin/settings")
@admin_required
def admin_settings():
    with connect_db() as c:
        return jsonify({r["setting_key"]:r["setting_value"] for r in c.execute("SELECT setting_key,setting_value FROM site_settings")})


@app.put("/api/admin/settings")
@admin_required
def admin_settings_update():
    require_csrf(); data=json_body()
    allowed={"hero_title":140,"hero_text":600,"hero_cta":40,"promo_title":140,"promo_text":300,"footer_notice":180,
             "contact_address":180,"contact_phone":40,"contact_hours":120}
    if not data or any(k not in allowed or not isinstance(v,str) or len(v)>allowed[k] for k,v in data.items()): abort(400)
    with connect_db() as c:
        for key,value in data.items():
            c.execute("INSERT INTO site_settings(setting_key,setting_value,updated_at) VALUES(?,?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=excluded.updated_at",(key,value.strip(),NOW()))
        audit(c,"update","site_settings","global",data)
    return jsonify(status="updated")


@app.get("/api/admin/content")
@admin_required
def admin_content():
    with connect_db() as c:
        rows=[]
        for r in c.execute("SELECT * FROM content_posts ORDER BY updated_at DESC"):
            item=dict(r); item["channels"]=json.loads(item.pop("channels_json")); rows.append(item)
        return jsonify(rows)


@app.post("/api/admin/content")
@admin_required
def admin_content_create():
    require_csrf(); d=json_body(); title=str(d.get("title"," ")).strip()[:140]; body=str(d.get("body"," ")).strip()[:5000]
    channels=d.get("channels",[])
    if len(title)<2 or len(body)<2 or not isinstance(channels,list) or not channels or any(x not in {"vk","max","telegram"} for x in channels): abort(400)
    status=str(d.get("status","draft"))
    if status not in {"draft","planned","approved"}: abort(400)
    with connect_db() as c:
        cur=c.execute("INSERT INTO content_posts(title,body,channels_json,scheduled_at,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
          (title,body,json.dumps(channels),str(d.get("scheduled_at","")),status,NOW(),NOW()))
        audit(c,"create","content",cur.lastrowid)
        return jsonify(id=cur.lastrowid),201


@app.patch("/api/admin/content/<int:post_id>")
@admin_required
def admin_content_update(post_id):
    require_csrf(); d=json_body(); fields={}
    for key in ("title","body","scheduled_at"):
        if key in d: fields[key]=str(d[key])[:5000]
    if "status" in d:
        if d["status"] not in {"draft","planned","approved","published","failed"}: abort(400)
        fields["status"]=d["status"]
    if "channels" in d:
        if not isinstance(d["channels"],list) or any(x not in {"vk","max","telegram"} for x in d["channels"]): abort(400)
        fields["channels_json"]=json.dumps(d["channels"])
    if not fields: abort(400)
    fields["updated_at"]=NOW()
    with connect_db() as c:
        cur=c.execute("UPDATE content_posts SET "+",".join(f"{k}=?" for k in fields)+" WHERE id=?",(*fields.values(),post_id))
        if not cur.rowcount: abort(404)
        audit(c,"update","content",post_id,fields)
    return jsonify(status="updated")


@app.post("/api/admin/content/<int:post_id>/publish")
@admin_required
def admin_content_publish(post_id):
    require_csrf()
    with connect_db() as c:
        post=c.execute("SELECT * FROM content_posts WHERE id=?",(post_id,)).fetchone()
        if not post: abort(404)
        channels=json.loads(post["channels_json"])
        missing=[]
        for channel in channels:
            if channel=="vk" and not (os.getenv("VK_GROUP_TOKEN") and os.getenv("VK_GROUP_ID")): missing.append("VK")
            if channel=="max" and not os.getenv("MAX_BOT_TOKEN"): missing.append("MAX")
            if channel=="telegram" and not os.getenv("TELEGRAM_BOT_TOKEN"): missing.append("Telegram")
        if missing:
            return jsonify(error="integration_not_configured",missing=missing,message="Публикация не отправлена. Сначала подключите и проверьте API.") ,409
        # Credentials alone are not proof of working API access. Real publisher adapters are intentionally not faked.
        return jsonify(error="publisher_adapter_pending",message="Ключи обнаружены, но адаптер публикации ещё не реализован и не проверен."),501


@app.get("/api/admin/integrations")
@admin_required
def admin_integrations():
    checks=[
      ("VK","VK_GROUP_TOKEN","VK_GROUP_ID"),("MAX Bot API","MAX_BOT_TOKEN",None),
      ("MAX Mini App HTTPS URL","MAX_MINIAPP_URL",None),("MAX order notifications","MAX_ADMIN_USER_ID",None),
      ("Telegram","TELEGRAM_BOT_TOKEN",None),("ЮKassa","YOOKASSA_SHOP_ID","YOOKASSA_SECRET_KEY"),
      ("PayKeeper","PAYKEEPER_SERVER_SECRET",None),("PostgreSQL","DATABASE_URL",None),
      ("Email","SMTP_HOST","SMTP_USER"),("SMS","SMS_PROVIDER_API_KEY",None),
      ("Yandex Maps","YANDEX_MAPS_API_KEY",None),
    ]
    with connect_db() as c:
        health_rows={r["provider"]:dict(r) for r in c.execute("SELECT provider,status,last_checked,detail FROM integration_health")}
    result=[]
    for name,a,b in checks:
        configured=bool(os.getenv(a)) and (bool(os.getenv(b)) if b else True)
        if name == "MAX Mini App HTTPS URL":
            configured = os.getenv(a, "").strip().startswith("https://")
        if name == "MAX order notifications":
            configured = os.getenv(a, "").strip().isdigit()
        result.append({"name":name,"status":"credentials_present_unverified" if configured else "not_configured",
                       "required_env":[x for x in (a,b) if x],"health":health_rows.get(name)})
    return jsonify(result)


@app.get("/api/admin/analytics")
@admin_required
def admin_analytics():
    try: days=max(1,min(int(request.args.get("days",30)),90))
    except ValueError: days=30
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=days)).isoformat(timespec="seconds")
    with connect_db() as c:
        rows=c.execute("SELECT substr(created_at,1,10) day,COUNT(*) orders,COALESCE(SUM(total_rub),0) revenue FROM orders WHERE created_at>=? GROUP BY day ORDER BY day",(cutoff,)).fetchall()
        events=c.execute("SELECT event_name,COUNT(*) count FROM events WHERE created_at>=? GROUP BY event_name",(cutoff,)).fetchall()
        top=c.execute("SELECT p.title,COUNT(*) qty FROM orders o,json_each(o.items_json) j JOIN products p ON p.id=json_extract(j.value,'$.id') WHERE o.created_at>=? GROUP BY p.id ORDER BY qty DESC LIMIT 5",(cutoff,)).fetchall()
        return jsonify(days=days,daily=[dict(r) for r in rows],events=[dict(r) for r in events],top_products=[dict(r) for r in top])



@app.get("/api/admin/loyalty/ledger")
@admin_required
def admin_loyalty_ledger():
    with connect_db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM ticket_ledger ORDER BY id DESC LIMIT 150")]
        totals = c.execute("SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) earned, COALESCE(SUM(CASE WHEN source_type='spin' THEN -delta ELSE 0 END),0) spent, COALESCE(SUM(CASE WHEN source_type LIKE '%reversal' THEN -delta ELSE 0 END),0) reversed FROM ticket_ledger").fetchone()
        return jsonify(rows=rows, earned=int(totals["earned"]), spent=int(totals["spent"]), reversed=int(totals["reversed"]), rub_per_ticket=get_loyalty_rate(c))



@app.patch("/api/admin/loyalty/rules")
@admin_required
def admin_loyalty_rules_update():
    require_csrf(); d=json_body()
    try: rate=int(d.get("rub_per_ticket"))
    except (TypeError,ValueError): abort(400)
    if not 100<=rate<=100000: abort(400)
    with connect_db() as c:
        c.execute("INSERT INTO site_settings(setting_key,setting_value,updated_at) VALUES('loyalty_rub_per_ticket',?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=excluded.updated_at",(str(rate),NOW()))
        audit(c,"update","loyalty_rule","rub_per_ticket",{"value":rate})
    return jsonify(status="updated",rub_per_ticket=rate)

@app.post("/api/admin/loyalty/award")
@admin_required
def admin_loyalty_award():
    require_csrf(); d=json_body()
    guest_id=str(d.get("guest_id", "")).strip()
    source_id=str(d.get("source_id", "")).strip()
    reason=str(d.get("reason", "Промоактивность вручную")).strip()
    try: amount=int(d.get("amount", 0))
    except (TypeError,ValueError): abort(400)
    guest_id=clean_guest_id(guest_id)
    if not source_id or len(source_id)>120 or not 1<=amount<=20 or len(reason)<3: abort(400)
    with connect_db() as c:
        created=credit_tickets(c,guest_id,amount,reason,"admin_promo",source_id,{"manual":True})
        if not created: return jsonify(error="duplicate_award",message="Для этой активности билеты уже начислялись."),409
        audit(c,"award_tickets","visitor",guest_id,{"amount":amount,"reason":reason,"source_id":source_id})
        balance=c.execute("SELECT tickets FROM visitors WHERE guest_id=?",(guest_id,)).fetchone()[0]
    return jsonify(status="credited",amount=amount,tickets=balance),201

@app.get("/api/admin/referrals")
@admin_required
def admin_referrals():
    with connect_db() as c:
        rows = [dict(r) for r in c.execute("SELECT a.*,rc.code AS referral_code FROM referral_attributions a LEFT JOIN referral_codes rc ON rc.owner_guest_id=a.referrer_guest_id ORDER BY a.created_at DESC LIMIT 250")]
        totals = c.execute("SELECT COUNT(*) total,SUM(CASE WHEN status='rewarded' THEN 1 ELSE 0 END) qualified,SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending,SUM(CASE WHEN status='reversed' THEN 1 ELSE 0 END) reversed FROM referral_attributions").fetchone()
        return jsonify(rows=rows, total=int(totals["total"] or 0), qualified=int(totals["qualified"] or 0), pending=int(totals["pending"] or 0), reversed=int(totals["reversed"] or 0),
                       minimum_order_rub=referral_setting(c,"referral_min_order_rub",1500,0,1000000),
                       referrer_tickets=referral_setting(c,"referral_inviter_tickets",10,0,100),
                       friend_tickets=referral_setting(c,"referral_friend_tickets",5,0,100),
                       tier_sailor_rub=referral_setting(c,"tier_sailor_rub",5000,0,1000000),
                       tier_captain_rub=referral_setting(c,"tier_captain_rub",15000,0,1000000),
                       tier_admiral_rub=referral_setting(c,"tier_admiral_rub",40000,0,1000000))


@app.patch("/api/admin/referrals/rules")
@admin_required
def admin_referral_rules_update():
    require_csrf(); d=json_body()
    try:
        minimum=int(d.get("minimum_order_rub")); inviter=int(d.get("referrer_tickets")); friend=int(d.get("friend_tickets"))
        sailor=int(d.get("tier_sailor_rub")); captain=int(d.get("tier_captain_rub")); admiral=int(d.get("tier_admiral_rub"))
    except (TypeError,ValueError): abort(400)
    if not 0<=minimum<=1000000 or not 0<=inviter<=100 or not 0<=friend<=100: abort(400)
    if not (0<=sailor<captain<admiral<=1000000): abort(400, description="tier_thresholds_must_be_strictly_ascending")
    with connect_db() as c:
        for key,value in [("referral_min_order_rub",minimum),("referral_inviter_tickets",inviter),("referral_friend_tickets",friend),("tier_sailor_rub",sailor),("tier_captain_rub",captain),("tier_admiral_rub",admiral)]:
            c.execute("INSERT INTO site_settings(setting_key,setting_value,updated_at) VALUES(?,?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=excluded.updated_at", (key,str(value),NOW()))
        audit(c,"update","referral_rules","global",{"minimum_order_rub":minimum,"referrer_tickets":inviter,"friend_tickets":friend})
    return jsonify(status="updated",minimum_order_rub=minimum,referrer_tickets=inviter,friend_tickets=friend,tier_sailor_rub=sailor,tier_captain_rub=captain,tier_admiral_rub=admiral)


@app.get("/api/admin/audit")
@admin_required
def admin_audit():
    with connect_db() as c: return jsonify([dict(r) for r in c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100")])


@app.get("/api/health")
def health():
    try:
        with connect_db() as c:
            c.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        return jsonify(status="degraded", service="rakovar-preview", dependency="database_unavailable"), 503
    return jsonify(status="ok", service="rakovar-preview", mode="demo" if DEMO_MODE else "production_guarded",
                   ordering="demo_only" if DEMO_MODE else "disabled_until_integrations_verified",
                   max_bot_token_configured=bool(MAX_BOT_TOKEN), max_miniapp_url_configured=bool(MAX_MINIAPP_URL),
                   integrations="credentials_are_not_connection_proof")


@app.errorhandler(400)
def bad_request(error):
    return jsonify(error="bad_request", message=getattr(error, "description", "Некорректный запрос")), 400


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"): return jsonify(error="not_found"),404
    return "Страница не найдена",404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
