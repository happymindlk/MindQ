#!/usr/bin/env python3
"""Compare SQLAlchemy models against the live Postgres schema.

Reports tables and columns declared on ``app.database.Base.metadata`` that are
missing from the database behind ``DATABASE_URL``, with an ``ALTER TABLE`` hint
for each missing column. Exits 1 on drift, 0 when the schema covers every model.

The fix for drift is normally to apply pending migrations
(``supabase migration up --local``); the generated SQL is a diagnostic aid.

Usage (from repo root, with backend venv activated):
  python scripts/check_schema_drift.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
# Settings reads `.env` relative to the working directory.
os.chdir(ROOT / "backend")

import asyncpg  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

import app.models  # noqa: E402,F401  (registers every model on Base.metadata)
from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402


async def fetch_live_columns(dsn: str) -> dict[str, set[str]]:
    """Read public-schema columns from Postgres.

    Args:
        dsn: asyncpg-compatible connection string.

    Returns:
        Mapping of table name to its set of column names.
    """
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "select table_name, column_name from information_schema.columns "
            "where table_schema = 'public'"
        )
    finally:
        await conn.close()
    live: dict[str, set[str]] = {}
    for row in rows:
        live.setdefault(row["table_name"], set()).add(row["column_name"])
    return live


def find_drift(live: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    """Diff model metadata against live columns.

    Args:
        live: Output of :func:`fetch_live_columns`.

    Returns:
        Tuple of (missing table names, ALTER TABLE statements for missing columns).
    """
    dialect = postgresql.dialect()
    missing_tables: list[str] = []
    alters: list[str] = []
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        if table.name not in live:
            missing_tables.append(table.name)
            continue
        for column in table.columns:
            if column.name in live[table.name]:
                continue
            col_type = column.type.compile(dialect=dialect)
            null_sql = "" if column.nullable else " NOT NULL"
            default_sql = ""
            if not column.nullable and column.default is not None and column.default.is_scalar:
                value = column.default.arg
                default_sql = f" DEFAULT {str(value).lower() if isinstance(value, bool) else repr(value)}"
            alters.append(
                f"ALTER TABLE public.{table.name} ADD COLUMN IF NOT EXISTS "
                f"{column.name} {col_type}{null_sql}{default_sql};"
            )
    return missing_tables, alters


async def main() -> int:
    dsn = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql")
    try:
        live = await fetch_live_columns(dsn)
    except (OSError, asyncpg.PostgresError) as exc:
        print(f"Could not read schema: {type(exc).__name__}: {exc}")
        return 2

    missing_tables, alters = find_drift(live)
    if not missing_tables and not alters:
        print(f"No schema drift: {len(Base.metadata.tables)} model tables match the database.")
        return 0

    print("Schema drift detected. Prefer applying migrations: supabase migration up --local")
    for name in missing_tables:
        print(f"  missing table: {name}")
    if alters:
        print("\nMissing columns (diagnostic SQL):")
        for stmt in alters:
            print(f"  {stmt}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
