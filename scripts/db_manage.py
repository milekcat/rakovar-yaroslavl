"""Apply additive migrations, inspect versions, or back up a SQLite preview.

DATABASE_URL selects PostgreSQL; no automatic fallback or destructive down
migration is provided. Credentials are read from the environment only.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage import StorageConfigurationError, connect_database, migrate
from scripts.db_transfer import open_source


def backup_sqlite(source, destination):
    output = Path(destination).resolve()
    if output.exists():
        raise ValueError("Backup destination already exists; existing files are never overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        with closing(open_source(source)) as original, closing(sqlite3.connect(output)) as copied:
            original.backup(copied)
            if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed")
        return {"status": "verified_backup", "bytes": output.stat().st_size}
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    commands.add_parser("status")
    backup = commands.add_parser("backup-sqlite")
    backup.add_argument("--source", required=True)
    backup.add_argument("--destination", required=True)
    args = parser.parse_args()
    try:
        if args.command == "backup-sqlite":
            result = backup_sqlite(args.source, args.destination)
        else:
            sqlite_path = os.environ.get("SQLITE_DB_PATH", str(ROOT / "rakovar.sqlite3"))
            if args.command == "status" and not os.environ.get("DATABASE_URL", "").strip() and not Path(sqlite_path).is_file():
                raise ValueError("SQLite database does not exist; status does not create it")
            with connect_database(sqlite_path) as connection:
                if args.command == "migrate":
                    result = {"backend": connection.dialect, "applied": migrate(connection)}
                else:
                    versions = [dict(row) for row in connection.execute("SELECT version,checksum,applied_at FROM schema_migrations ORDER BY version")]
                    result = {"backend": connection.dialect, "migrations": versions}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (StorageConfigurationError, sqlite3.Error, OSError, ValueError) as error:
        print(f"Database command stopped: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
