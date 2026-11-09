"""Opt-in PostgreSQL suite isolation; never target an operator's business schema."""
import os
import uuid
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import pytest


@pytest.fixture(autouse=True)
def isolated_postgres_schema(monkeypatch):
    if os.environ.get("RAKOVAR_TEST_POSTGRES") != "1":
        yield
        return
    base = os.environ.get("TEST_POSTGRES_URL")
    if not base:
        pytest.fail("RAKOVAR_TEST_POSTGRES=1 requires a disposable TEST_POSTGRES_URL")
    import psycopg
    from psycopg import sql

    schema = "rakovar_suite_" + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query))
    query["options"] = "-c search_path=" + schema
    monkeypatch.setenv("DATABASE_URL", urlunsplit(parts._replace(query=urlencode(query, quote_via=quote))))
    try:
        yield
    finally:
        with psycopg.connect(base, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
