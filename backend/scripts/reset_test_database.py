#!/usr/bin/env python3
"""Reset the disposable PostgreSQL schema used by CI/integration tests.

This is intentionally stricter than a generic "drop everything" helper:
it only runs in a test environment and only against a test-named database.
The workflow uses it before re-applying Alembic migrations so focused test
steps do not inherit rows or schema state left by earlier integration suites.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


def _database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""


def _assert_disposable(url: str) -> None:
    environment = os.environ.get("ENVIRONMENT", "").lower()
    ci = os.environ.get("CI", "").lower() == "true"
    if environment != "test" and not ci:
        raise RuntimeError(
            "Refusing to reset database outside ENVIRONMENT=test or CI=true."
        )

    database = make_url(url).database or ""
    if database != "test" and not database.endswith("_test"):
        raise RuntimeError(
            f"Refusing to reset non-test database {database!r}; expected 'test' "
            "or a name ending in '_test'."
        )


async def _reset(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
    finally:
        await engine.dispose()


def main() -> int:
    url = _database_url()
    if not url:
        print("DATABASE_URL or TEST_DATABASE_URL is required", file=sys.stderr)
        return 2

    try:
        _assert_disposable(url)
        asyncio.run(_reset(url))
    except Exception as exc:
        print(f"reset_test_database failed: {exc}", file=sys.stderr)
        return 1

    print("Reset public schema for disposable test database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
