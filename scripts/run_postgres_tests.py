"""Run real PostgreSQL and pytest in one process namespace using a disposable cluster.

Usage: .venv/bin/python scripts/run_postgres_tests.py --postgres-bin /path/to/bin
       .venv/bin/python scripts/run_postgres_tests.py --postgres-bin /path/to/bin -- -q tests/test_storage.py
No production database or existing PostgreSQL cluster is used.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", default=os.environ.get("RAKOVAR_POSTGRES_BIN", ""))
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    binary_dir = Path(args.postgres_bin) if args.postgres_bin else Path(shutil.which("postgres") or ".").parent
    binaries = {name: str(binary_dir / name) for name in ("postgres", "initdb")}
    if not all(Path(path).is_file() for path in binaries.values()):
        parser.error("Provide an installed PostgreSQL bin directory with --postgres-bin")
    import psycopg

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="rakovar-pg-test-") as temporary:
        work = Path(temporary)
        data = work / "data"
        subprocess.run([binaries["initdb"], "-D", str(data), "--auth=trust", "--no-locale", "-E", "UTF8", "-U", "rakovar_test"],
                       stdout=subprocess.DEVNULL, check=True)
        url = f"postgresql://rakovar_test@127.0.0.1:{port}/postgres"
        with (work / "postgres.log").open("w+") as log:
            process = subprocess.Popen([binaries["postgres"], "-D", str(data), "-p", str(port),
                "-c", "unix_socket_directories=", "-c", "listen_addresses=127.0.0.1",
                "-c", "fsync=off", "-c", "synchronous_commit=off", "-c", "full_page_writes=off"],
                stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError("Disposable PostgreSQL exited: " + log.read()[-3000:])
                    try:
                        with psycopg.connect(url, connect_timeout=1) as connection:
                            version = connection.execute("SHOW server_version").fetchone()[0]
                        break
                    except psycopg.OperationalError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Disposable PostgreSQL did not become ready") from None
                        time.sleep(.1)
                print(f"Testing against local disposable PostgreSQL {version}", flush=True)
                env = os.environ.copy()
                env.update(TEST_POSTGRES_URL=url, RAKOVAR_TEST_POSTGRES="1", RAKOVAR_POSTGRES_BIN=str(binary_dir))
                test_args = args.pytest_args
                if test_args[:1] == ["--"]:
                    test_args = test_args[1:]
                return subprocess.run([sys.executable, "-m", "pytest", *(test_args or ["-q"])],
                    cwd=Path(__file__).resolve().parents[1], env=env).returncode
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
