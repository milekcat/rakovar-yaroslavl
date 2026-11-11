"""Recovery and copy tests use only synthetic local records."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
from urllib.parse import parse_qs, urlsplit
import uuid

import pytest

from scripts.db_manage import backup_sqlite
import scripts.db_transfer as importer
import storage


def synthetic_database(tmp_path):
    path = tmp_path / "source.sqlite3"
    with storage.connect_database(path, database_url="") as c:
        storage.migrate(c)
        c.execute("INSERT INTO visitors(guest_id,tickets,created_at) VALUES(?,?,?)", ("synthetic-guest", 7, "now"))
        c.execute("INSERT INTO events(id,event_name,created_at) VALUES(?,?,?)", (7, "synthetic-event", "now"))
        c.execute("""INSERT INTO orders(id,created_at,customer_label,contact_label,delivery_mode,
            address_label,items_json,subtotal_rub,discount_rub,delivery_rub,total_rub,status,is_demo)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", ("DEMO-TRANSFER", "now", "ДЕМО-ПОКУПАТЕЛЬ", "НЕ СОХРАНЕНО", "pickup", "НЕ СОХРАНЕНО", "[]", 0, 0, 0, 0, "demo_received", 1))
    return path


def test_dry_run_is_read_only_and_does_not_connect_target(tmp_path, monkeypatch):
    source = synthetic_database(tmp_path)
    before = source.read_bytes()
    monkeypatch.setattr(importer, "connect_database", lambda *a, **k: pytest.fail("Dry-run must not connect to PostgreSQL"))
    result = importer.transfer(source, "postgresql://unreachable", apply=False)
    assert result["mode"] == "dry_run" and result["total_rows"] == 3
    assert source.read_bytes() == before


def test_sqlite_backup_is_recoverable_without_overwrite(tmp_path):
    source = synthetic_database(tmp_path)
    backup = tmp_path / "backup.sqlite3"
    assert backup_sqlite(source, backup)["status"] == "verified_backup"
    assert backup.stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(backup)) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("SELECT tickets FROM visitors").fetchone()[0] == 7
        assert c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 7
    with pytest.raises(ValueError, match="already exists"):
        backup_sqlite(source, backup)


def test_preview_import_rejects_personal_contact_records(tmp_path):
    source = synthetic_database(tmp_path)
    with storage.connect_database(source, database_url="") as c:
        c.execute("UPDATE orders SET contact_label=?", ("synthetic-but-outside-import-boundary",))
    with pytest.raises(importer.TransferError, match="outside this preview importer"):
        importer.transfer(source)


def test_preview_import_rejects_unknown_tables(tmp_path):
    source = synthetic_database(tmp_path)
    with storage.connect_database(source, database_url="") as c:
        c.execute("CREATE TABLE unknown_records(value TEXT)")
    with pytest.raises(importer.TransferError, match="Unknown source tables"):
        importer.transfer(source)


@pytest.fixture()
def postgres_target():
    if os.environ.get("RAKOVAR_TEST_POSTGRES") != "1":
        pytest.skip("Run via scripts/run_postgres_tests.py for a disposable PostgreSQL target")
    return os.environ["DATABASE_URL"]


def test_transfer_restores_counts_and_identity_sequences(tmp_path, postgres_target):
    source = synthetic_database(tmp_path)
    result = importer.transfer(source, postgres_target, apply=True)
    assert result["mode"] == "applied" and result["total_rows"] == 3
    with storage.connect_database("unused", database_url=postgres_target) as c:
        assert c.execute("SELECT tickets FROM visitors").fetchone()[0] == 7
        assert c.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        inserted = c.execute("INSERT INTO events(event_name,created_at) VALUES(?,?)", ("after-copy", "now"))
        assert inserted.lastrowid == 8
    with pytest.raises(importer.TransferError, match="must be empty"):
        importer.transfer(source, postgres_target, apply=True)
    with storage.connect_database("unused", database_url=postgres_target) as c:
        assert c.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 1


def test_transfer_unknown_column_rolls_back_target_migrations(tmp_path, postgres_target):
    source = synthetic_database(tmp_path)
    with storage.connect_database(source, database_url="") as c:
        c.execute("ALTER TABLE visitors ADD COLUMN unrecognized_value TEXT")
    with pytest.raises(importer.TransferError, match="unsupported"):
        importer.transfer(source, postgres_target, apply=True)
    with storage.connect_database("unused", database_url=postgres_target) as c:
        assert c.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=current_schema()").fetchone()[0] == 0


def test_transfer_failure_rolls_back_identity_restart(tmp_path, postgres_target):
    source = synthetic_database(tmp_path)
    with storage.connect_database(source, database_url="") as c:
        # audit_log is copied after events and thus fails after the events restart.
        c.execute("ALTER TABLE audit_log ADD COLUMN unrecognized_value TEXT")
    with storage.connect_database("unused", database_url=postgres_target) as c:
        storage.migrate(c)
        c.execute("ALTER TABLE events ALTER COLUMN id RESTART WITH 500")
    with pytest.raises(importer.TransferError, match="unsupported"):
        importer.transfer(source, postgres_target, apply=True)
    with storage.connect_database("unused", database_url=postgres_target) as c:
        assert c.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 0
        inserted = c.execute("INSERT INTO events(event_name,created_at) VALUES(?,?)", ("after-rollback", "now"))
        assert inserted.lastrowid == 500


def test_postgres_dump_restores_into_separate_disposable_database(tmp_path, postgres_target):
    import psycopg
    from psycopg import sql
    if not os.environ.get("RAKOVAR_POSTGRES_BIN"):
        pytest.skip("Set RAKOVAR_POSTGRES_BIN to matching pg_dump/pg_restore binaries")
    bin_dir = Path(os.environ["RAKOVAR_POSTGRES_BIN"])
    if not (bin_dir / "pg_dump").is_file() or not (bin_dir / "pg_restore").is_file():
        pytest.skip("Matching pg_dump/pg_restore binaries are not installed")
    source = synthetic_database(tmp_path)
    importer.transfer(source, postgres_target, apply=True)
    parts = urlsplit(postgres_target)
    options = parse_qs(parts.query)["options"][0]
    schema = options.split("search_path=", 1)[1]
    restored_name = "rakovar_restore_" + uuid.uuid4().hex
    base = os.environ["TEST_POSTGRES_URL"]
    environment = os.environ.copy()
    # All connection values here belong to the test runner's loopback-only,
    # passwordless disposable cluster. No external credential is propagated.
    environment.update(PGHOST=parts.hostname, PGPORT=str(parts.port), PGUSER=parts.username,
                       PGDATABASE=parts.path.lstrip("/"))
    environment.pop("PGPASSWORD", None)
    environment.pop("PGSERVICE", None)
    environment.pop("PGOPTIONS", None)
    dump = tmp_path / "verified.dump"
    subprocess.run([str(bin_dir / "pg_dump"), "--format=custom", "--no-owner", "--no-acl",
                    "--schema=" + schema, "--file=" + str(dump)], env=environment, check=True, capture_output=True)
    with psycopg.connect(base, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored_name)))
    try:
        environment["PGDATABASE"] = restored_name
        subprocess.run([str(bin_dir / "pg_restore"), "--dbname=" + restored_name,
                        "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", str(dump)],
                       env=environment, check=True, capture_output=True)
        with psycopg.connect(host=parts.hostname, port=parts.port, user=parts.username,
                            dbname=restored_name, options="-c search_path=" + schema) as c:
            assert c.execute("SELECT tickets FROM visitors").fetchone()[0] == 7
            assert c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 7
            assert c.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
            assert c.execute("SELECT event_name FROM events").fetchone()[0] == "synthetic-event"
    finally:
        with psycopg.connect(base, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(restored_name)))
