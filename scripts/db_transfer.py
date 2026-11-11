"""Inspect a SQLite preview and optionally copy it to an empty PostgreSQL schema.

Dry-run is the default and never connects to the target. Target credentials are
read from an environment variable, never from command arguments or output.
Staff credentials, sessions, MFA seeds and transient leases are not transferred.
This preview importer intentionally rejects commercial/personal contact records.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage import IDENTITY_TABLES, StorageConfigurationError, connect_database, migrate


TABLES = (
    "products", "orders", "visitors", "prizes", "spins", "promotions", "contests",
    "contest_entries", "contest_winners", "content_posts", "site_settings", "events",
    "integration_health", "ticket_ledger", "referral_codes", "referral_attributions",
    "audit_log", "operation_receipts", "order_status_history", "max_webhook_events",
    "provider_deliveries", "provider_events",
    "shop_catalog_overrides", "shop_inventory", "shop_stock_ledger", "shop_bonus_ledger", "shop_notifications", "shop_outbox",
)
SKIPPED = frozenset({"schema_migrations", "max_webhook_leases", "staff_accounts",
    "staff_sessions", "staff_mfa", "staff_login_events", "staff_login_guards", "provider_connections", "shop_profiles", "shop_accounts", "shop_sessions", "shop_order_details", "shop_media"})
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TransferError(ValueError):
    pass


def open_source(path):
    source = Path(path).resolve(strict=True)
    if not source.is_file():
        raise TransferError("Source must be a SQLite file")
    connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def inspect_source(connection):
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise TransferError("Source SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise TransferError("Source SQLite foreign key check failed")
    names = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    unknown = names - set(TABLES) - SKIPPED
    if unknown:
        raise TransferError("Unknown source tables require an explicit migration: " + ", ".join(sorted(unknown)))
    if "shop_order_details" in names and connection.execute("SELECT COUNT(*) FROM shop_order_details").fetchone()[0]:
        raise TransferError("Encrypted customer orders require a dedicated protected migration")
    if "orders" in names:
        columns = {r[1] for r in connection.execute("PRAGMA table_info(orders)")}
        required = {"is_demo", "customer_label", "contact_label", "address_label"}
        if not required <= columns:
            raise TransferError("Order schema cannot establish the preview data boundary")
        unsafe = connection.execute("""SELECT COUNT(*) FROM orders WHERE is_demo<>1
            OR customer_label<>'ДЕМО-ПОКУПАТЕЛЬ' OR contact_label<>'НЕ СОХРАНЕНО'
            OR address_label<>'НЕ СОХРАНЕНО'""").fetchone()[0]
        if unsafe:
            raise TransferError("Commercial or personal contact records are outside this preview importer")
    tables = []
    for name in TABLES:
        if name in names:
            columns = [r[1] for r in connection.execute(f'PRAGMA table_info("{name}")')]
            if not all(IDENTIFIER.fullmatch(column) for column in columns):
                raise TransferError("Unsafe source column name")
            tables.append({"name": name, "rows": connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0], "columns": columns})
    return {"mode": "dry_run", "tables": tables, "skipped_tables": sorted(names & SKIPPED),
            "total_rows": sum(table["rows"] for table in tables)}


def transfer(source_path, target_url=None, *, apply=False):
    with closing(open_source(source_path)) as source:
        # Hold a read snapshot for counts and all batches, including concurrent
        # SQLite source writes. The operator should still stop writers at cutover.
        source.execute("BEGIN")
        plan = inspect_source(source)
        if not apply:
            return plan
        if not target_url or urlsplit(target_url).scheme not in {"postgres", "postgresql"}:
            raise TransferError("Apply requires a PostgreSQL target in the configured environment variable")
        with connect_database("unused.sqlite3", database_url=target_url) as target:
            migrate(target)
            for table in TABLES:
                if target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]:
                    raise TransferError("Target business tables must be empty; no merge or overwrite is performed")
            for table in plan["tables"]:
                name, columns = table["name"], table["columns"]
                target_columns = {r[1] for r in target.execute(f"PRAGMA table_info({name})")}
                if not set(columns) <= target_columns:
                    raise TransferError("Source has columns unsupported by the target migration")
                quoted = ",".join(f'"{column}"' for column in columns)
                insert = f'INSERT INTO "{name}"({quoted}) VALUES({",".join("?" for _ in columns)})'
                cursor = source.execute(f'SELECT {quoted} FROM "{name}"')
                while batch := cursor.fetchmany(500):
                    target.executemany(insert, [tuple(row) for row in batch])
                if target.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] != table["rows"]:
                    raise TransferError("Post-copy row count did not match; transfer rolled back")
                if name in IDENTITY_TABLES and table["rows"]:
                    maximum = target.execute(f'SELECT MAX(id) FROM "{name}"').fetchone()[0]
                    # RESTART is transactional; setval() would survive a later
                    # rollback and change the sequence of an otherwise untouched target.
                    target.execute(f'ALTER TABLE "{name}" ALTER COLUMN id RESTART WITH {int(maximum) + 1}')
            plan["mode"] = "applied"
        return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target-url-env", default="DATABASE_URL")
    parser.add_argument("--apply", action="store_true", help="Copy to an empty target in one transaction")
    args = parser.parse_args()
    try:
        result = transfer(args.source, os.environ.get(args.target_url_env, ""), apply=args.apply)
    except (TransferError, StorageConfigurationError, sqlite3.Error, OSError) as error:
        # Adapter errors are deliberately sanitized; never print an underlying URL.
        print(f"Transfer stopped: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
