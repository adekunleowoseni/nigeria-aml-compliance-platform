"""DDL for aml_transactions / aml_alerts (Postgres system-of-record)."""

from __future__ import annotations

from pathlib import Path

from app.db.postgres_client import PostgresClient


async def ensure_aml_runtime_tables(pg: PostgresClient) -> None:
    sql_path = Path(__file__).resolve().parents[2] / "sql" / "aml_runtime_stores.sql"
    if not sql_path.is_file():
        raise FileNotFoundError(f"Missing {sql_path}")
    body = sql_path.read_text(encoding="utf-8")
    for raw in body.split(";"):
        stmt = raw.strip()
        if not stmt or stmt.startswith("--"):
            continue
        await pg.execute(stmt)
