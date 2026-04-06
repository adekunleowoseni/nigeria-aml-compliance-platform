"""Persist admin-uploaded sanctions, PEP, and adverse-media reference lists (JSONB)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.db.postgres_client import PostgresClient


async def ensure_reference_lists_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS aml_reference_lists (
            list_type TEXT PRIMARY KEY,
            items JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by TEXT
        );
        """
    )
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS aml_reference_screening_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            customers_scanned INTEGER NOT NULL DEFAULT 0,
            hits_total INTEGER NOT NULL DEFAULT 0,
            hits JSONB NOT NULL DEFAULT '[]'::jsonb,
            notes TEXT
        );
        """
    )


async def load_all_lists(pg: PostgresClient) -> Dict[str, List[Dict[str, Any]]]:
    rows = await pg.fetch("SELECT list_type, items FROM aml_reference_lists")
    out: Dict[str, List[Dict[str, Any]]] = {"sanctions": [], "pep": [], "adverse_media": []}
    for r in rows:
        lt = str(r.get("list_type") or "")
        if lt not in out:
            continue
        raw = r.get("items")
        if raw is None:
            items: List[Any] = []
        elif isinstance(raw, str):
            items = json.loads(raw)
        elif isinstance(raw, list):
            items = raw
        else:
            items = []
        if isinstance(items, list):
            out[lt] = [x for x in items if isinstance(x, dict)]
    return out


async def upsert_list(
    pg: PostgresClient,
    *,
    list_type: str,
    items: List[Dict[str, Any]],
    updated_by: str,
) -> None:
    await pg.execute(
        """
        INSERT INTO aml_reference_lists (list_type, items, updated_by, updated_at)
        VALUES ($1, $2::jsonb, $3, NOW())
        ON CONFLICT (list_type) DO UPDATE SET
            items = EXCLUDED.items,
            updated_by = EXCLUDED.updated_by,
            updated_at = NOW();
        """,
        list_type,
        json.dumps(items, default=str),
        updated_by[:500] if updated_by else None,
    )


async def insert_screening_run(
    pg: PostgresClient,
    *,
    customers_scanned: int,
    hits_total: int,
    hits: List[Dict[str, Any]],
    notes: Optional[str] = None,
) -> None:
    await pg.execute(
        """
        INSERT INTO aml_reference_screening_runs (customers_scanned, hits_total, hits, notes)
        VALUES ($1, $2, $3::jsonb, $4);
        """,
        customers_scanned,
        hits_total,
        json.dumps(hits, default=str),
        (notes or "")[:2000] or None,
    )


async def fetch_latest_screening_run(pg: PostgresClient) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow(
        """
        SELECT run_at, customers_scanned, hits_total, hits, notes
        FROM aml_reference_screening_runs
        ORDER BY run_at DESC
        LIMIT 1;
        """
    )
    if not row:
        return None
    return dict(row)
