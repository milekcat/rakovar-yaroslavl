"""Run against SQLite and, when configured, an isolated PostgreSQL schema.

TEST_POSTGRES_URL must refer to a disposable test database, never production.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import uuid
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import pytest

import storage


@pytest.fixture(params=["sqlite", "postgresql"])
def database(request, tmp_path):
    path = tmp_path / "local.sqlite3"
    if request.param == "sqlite":
        url = ""
        yield lambda: storage.connect_database(path, database_url=url)
        return
    base = os.environ.get("TEST_POSTGRES_URL")
    if not base:
        pytest.skip("TEST_POSTGRES_URL is not configured")
    import psycopg
    from psycopg import sql
    schema = "storage_test_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query))
    query["options"] = "-c search_path=" + schema
    url = urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))
    try:
        yield lambda: storage.connect_database(path, database_url=url)
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_versioned_migrations_are_idempotent_and_preserve_rows(database):
    with database() as connection:
        assert storage.migrate(connection) == ["0001_core", "0002_legacy_columns", "0003_staff_and_safety", "0004_provider_connections", "0005_store_operations", "0006_shop_media", "0007_catalog_overrides"]
        connection.execute("INSERT INTO visitors(guest_id,tickets,created_at) VALUES(?,?,?)", ("visitor-migration", 7, "2026-11-09"))
    with database() as connection:
        assert storage.migrate(connection) == []
        row = connection.execute("SELECT * FROM visitors WHERE guest_id=?", ("visitor-migration",)).fetchone()
        assert row["tickets"] == 7
        assert dict(row)["guest_id"] == row[0] == "visitor-migration"
        columns = {row[1] for row in connection.execute("PRAGMA table_info(prizes)")}
        assert "reward_value" in columns


def test_legacy_schema_adds_missing_columns_without_data_loss(database):
    with database() as connection:
        connection.execute("CREATE TABLE prizes(id TEXT PRIMARY KEY,title TEXT NOT NULL,kind TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',stock INTEGER NOT NULL DEFAULT 0,weight INTEGER NOT NULL DEFAULT 1,partner TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1)")
        connection.execute("INSERT INTO prizes(id,title,kind,stock) VALUES(?,?,?,?)", ("old-prize", "Legacy", "gift", 3))
        storage.migrate(connection)
    with database() as connection:
        row = connection.execute("SELECT * FROM prizes WHERE id=?", ("old-prize",)).fetchone()
        assert row["stock"] == 3 and row["reward_value"] == 0


def test_transaction_rolls_back_all_statements(database):
    with database() as connection:
        storage.migrate(connection)
    with pytest.raises(RuntimeError):
        with database() as connection:
            connection.execute("INSERT INTO visitors(guest_id,tickets,created_at) VALUES(?,?,?)", ("rollback-user", 2, "now"))
            connection.execute("INSERT INTO ticket_ledger(guest_id,delta,reason,source_type,source_id,created_at) VALUES(?,?,?,?,?,?)", ("rollback-user", 2, "test", "test", "rollback", "now"))
            raise RuntimeError("abort entire workflow")
    with database() as connection:
        assert connection.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM ticket_ledger").fetchone()[0] == 0


def test_integrity_error_does_not_poison_outer_transaction(database):
    with database() as connection:
        storage.migrate(connection)
        connection.execute("INSERT INTO visitors(guest_id,tickets,created_at) VALUES(?,?,?)", ("existing-user", 2, "now"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO visitors(guest_id,tickets,created_at) VALUES(?,?,?)", ("existing-user", 99, "now"))
        connection.execute("UPDATE visitors SET tickets=tickets+1 WHERE guest_id=?", ("existing-user",))
    with database() as connection:
        assert connection.execute("SELECT tickets FROM visitors WHERE guest_id=?", ("existing-user",)).fetchone()[0] == 3


def test_generated_id_ignore_and_literal_qmarks(database):
    with database() as connection:
        storage.migrate(connection)
        inserted = connection.execute("INSERT INTO events(event_name,created_at) VALUES(?,?)", ("a?b%", "now"))
        assert inserted.lastrowid > 0
        assert connection.execute("SELECT last_insert_rowid()").fetchone()[0] == inserted.lastrowid
        row = connection.execute("SELECT '?' literal, '%test' wildcard, event_name FROM events WHERE id=?", (inserted.lastrowid,)).fetchone()
        assert list(dict(row).values()) == ["?", "%test", "a?b%"]
        assert connection.execute("INSERT OR IGNORE INTO site_settings(setting_key,setting_value,updated_at) VALUES(?,?,?)", ("one", "first", "now")).rowcount == 1
        assert connection.execute("INSERT OR IGNORE INTO site_settings(setting_key,setting_value,updated_at) VALUES(?,?,?)", ("one", "ignored", "now")).rowcount == 0
        connection.execute("INSERT OR REPLACE INTO site_settings(setting_key,setting_value,updated_at) VALUES(?,?,?)", ("one", "updated", "now"))
        assert connection.execute("SELECT setting_value FROM site_settings WHERE setting_key=?", ("one",)).fetchone()[0] == "updated"


def test_parallel_legacy_read_modify_write_is_serialized(database):
    with database() as connection:
        storage.migrate(connection)
        connection.execute("INSERT INTO visitors(guest_id,tickets,created_at) VALUES(?,?,?)", ("parallel-user", 0, "now"))

    def increment(_):
        with database() as connection:
            old = connection.execute("SELECT tickets FROM visitors WHERE guest_id=?", ("parallel-user",)).fetchone()[0]
            connection.execute("UPDATE visitors SET tickets=? WHERE guest_id=?", (old + 1, "parallel-user"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(increment, range(12)))
    with database() as connection:
        assert connection.execute("SELECT tickets FROM visitors WHERE guest_id=?", ("parallel-user",)).fetchone()[0] == 12


def test_json_sales_analytics_matches_catalog(database):
    with database() as connection:
        storage.migrate(connection)
        connection.execute("INSERT INTO products(id,title,category,price,unit,created_at) VALUES(?,?,?,?,?,?)", ("shrimp", "Креветки", "Sea", 500, "шт", "now"))
        connection.execute("""INSERT INTO orders(id,created_at,customer_label,contact_label,delivery_mode,address_label,
            items_json,subtotal_rub,discount_rub,delivery_rub,total_rub,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", ("order-test", "2026-11-09", "demo", "demo", "pickup", "demo", '[{"id":"shrimp","qty":2}]', 1000, 0, 0, 1000, "paid"))
        top = storage.top_products(connection, "2026-11-01")
        assert len(top) == 1 and top[0]["title"] == "Креветки" and top[0]["qty"] == 1


def test_migration_checksum_rejects_edits(database, monkeypatch, tmp_path):
    with database() as connection:
        storage.migrate(connection)
    directory = tmp_path / "changed"
    directory.mkdir()
    for path in storage.MIGRATIONS.iterdir():
        if path.suffix in {".sql", ".json"}:
            (directory / path.name).write_bytes(path.read_bytes() + (b"\n-- changed\n" if path.suffix == ".sql" else b"\n"))
    monkeypatch.setattr(storage, "MIGRATIONS", directory)
    with pytest.raises(storage.StorageConfigurationError, match="checksum"):
        with database() as connection:
            storage.migrate(connection)


def test_invalid_database_url_never_falls_back_to_local(tmp_path):
    target = tmp_path / "must-not-exist.sqlite3"
    with pytest.raises(storage.StorageConfigurationError):
        with storage.connect_database(target, database_url="mysql://invalid"):
            pass
    assert not target.exists()
