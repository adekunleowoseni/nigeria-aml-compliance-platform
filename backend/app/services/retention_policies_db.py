"""
Configurable retention (CBN 5.11.b.ii) + legal holds (NDPA). TEXT user refs (no users table).

audit_events: policies may reference it but the runner never DELETEs hash-chained rows — only logs evaluation.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.db.postgres_client import PostgresClient

DEFAULT_POLICIES: List[Tuple[str, int, str]] = [
    ("alert", 365, "DELETE"),
    ("transaction", 365, "DELETE"),
    ("report", 1825, "DELETE"),
    ("customer_kyc", 2555, "ANONYMIZE"),
    ("audit_event", 2555, "ARCHIVE"),
]


async def ensure_retention_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_policies (
            id SERIAL PRIMARY KEY,
            record_type VARCHAR(50) NOT NULL UNIQUE,
            retention_days INTEGER NOT NULL,
            action VARCHAR(20) NOT NULL DEFAULT 'DELETE',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_by TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT retention_policies_action_chk CHECK (
              action IN ('DELETE', 'ARCHIVE', 'ANONYMIZE')
            )
        );
        """
    )
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS legal_holds (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            record_type VARCHAR(50) NOT NULL,
            record_id VARCHAR(255) NOT NULL,
            hold_reason TEXT,
            placed_by TEXT,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_legal_holds_lookup ON legal_holds (record_type, record_id);
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_legal_holds_expires ON legal_holds (expires_at);
        """
    )
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_soft_delete_registry (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            record_type VARCHAR(50) NOT NULL,
            record_id VARCHAR(512) NOT NULL,
            soft_deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            hard_purge_after TIMESTAMPTZ NOT NULL,
            snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            anonymized BOOLEAN NOT NULL DEFAULT FALSE,
            UNIQUE (record_type, record_id)
        );
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_retention_soft_purge ON retention_soft_delete_registry (hard_purge_after);
        """
    )
    # KYC soft-delete column
    await pg.execute(
        """
        ALTER TABLE aml_customer_kyc ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
        """
    )
    await pg.execute(
        """
        ALTER TABLE aml_customer_kyc ADD COLUMN IF NOT EXISTS anonymized_at TIMESTAMPTZ;
        """
    )

    for rt, days, action in DEFAULT_POLICIES:
        await pg.execute(
            """
            INSERT INTO retention_policies (record_type, retention_days, action, is_active)
            VALUES ($1, $2, $3, TRUE)
            ON CONFLICT (record_type) DO NOTHING
            """,
            rt,
            days,
            action,
        )


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            out[k] = int(v) if v == int(v) else float(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out


async def list_policies(pg: PostgresClient) -> List[Dict[str, Any]]:
    rows = await pg.fetch("SELECT * FROM retention_policies ORDER BY record_type")
    return [_row(dict(r)) for r in rows]


async def upsert_policy(
    pg: PostgresClient,
    *,
    record_type: str,
    retention_days: int,
    action: str,
    is_active: bool,
    updated_by: Optional[str],
) -> Dict[str, Any]:
    rt = record_type.strip().lower()
    act = action.strip().upper()
    if act not in ("DELETE", "ARCHIVE", "ANONYMIZE"):
        raise ValueError("invalid action")
    row = await pg.fetchrow(
        """
        INSERT INTO retention_policies (record_type, retention_days, action, is_active, updated_by, updated_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        ON CONFLICT (record_type) DO UPDATE SET
          retention_days = EXCLUDED.retention_days,
          action = EXCLUDED.action,
          is_active = EXCLUDED.is_active,
          updated_by = EXCLUDED.updated_by,
          updated_at = NOW()
        RETURNING *
        """,
        rt,
        int(retention_days),
        act,
        bool(is_active),
        updated_by,
    )
    return _row(dict(row)) or {}


async def get_active_policy(pg: PostgresClient, record_type: str) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow(
        """
        SELECT * FROM retention_policies
        WHERE record_type = $1 AND is_active = TRUE
        """,
        record_type.strip().lower(),
    )
    return _row(dict(row)) if row else None


async def has_active_legal_hold(pg: PostgresClient, record_type: str, record_id: str) -> bool:
    rt = record_type.strip().lower()
    rid = (record_id or "").strip()
    v = await pg.fetchval(
        """
        SELECT 1 FROM legal_holds
        WHERE (expires_at IS NULL OR expires_at > NOW())
          AND record_type = $1
          AND (record_id = $2 OR record_id = '*')
        LIMIT 1
        """,
        rt,
        rid,
    )
    return v is not None


async def insert_legal_hold(
    pg: PostgresClient,
    *,
    record_type: str,
    record_id: str,
    hold_reason: Optional[str],
    placed_by: Optional[str],
    expires_at: Optional[datetime],
) -> Dict[str, Any]:
    row = await pg.fetchrow(
        """
        INSERT INTO legal_holds (record_type, record_id, hold_reason, placed_by, expires_at)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        record_type.strip().lower(),
        (record_id or "").strip() or "*",
        (hold_reason or "").strip() or None,
        placed_by,
        expires_at,
    )
    return _row(dict(row)) or {}


async def delete_legal_hold(pg: PostgresClient, hold_id: str) -> bool:
    try:
        UUID(hold_id)
    except ValueError:
        return False
    r = await pg.execute("DELETE FROM legal_holds WHERE id = $1::uuid", hold_id)
    return str(r).strip().endswith("1")


async def list_legal_holds(pg: PostgresClient, *, limit: int = 200) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 500))
    rows = await pg.fetch(
        """
        SELECT * FROM legal_holds
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [_row(dict(r)) for r in rows]


async def registry_get(pg: PostgresClient, record_type: str, record_id: str) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow(
        """
        SELECT * FROM retention_soft_delete_registry
        WHERE record_type = $1 AND record_id = $2
        """,
        record_type.strip().lower(),
        record_id,
    )
    return _row(dict(row)) if row else None


async def registry_insert(
    pg: PostgresClient,
    *,
    record_type: str,
    record_id: str,
    snapshot: Dict[str, Any],
    hard_purge_after: datetime,
) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow(
        """
        INSERT INTO retention_soft_delete_registry (
          record_type, record_id, soft_deleted_at, hard_purge_after, snapshot
        ) VALUES ($1, $2, NOW(), $3, $4::jsonb)
        ON CONFLICT (record_type, record_id) DO UPDATE SET
          snapshot = EXCLUDED.snapshot,
          hard_purge_after = EXCLUDED.hard_purge_after,
          soft_deleted_at = retention_soft_delete_registry.soft_deleted_at
        RETURNING *
        """,
        record_type.strip().lower(),
        record_id,
        hard_purge_after,
        snapshot,
    )
    return _row(dict(row)) if row else None


async def registry_delete(pg: PostgresClient, record_type: str, record_id: str) -> None:
    await pg.execute(
        "DELETE FROM retention_soft_delete_registry WHERE record_type = $1 AND record_id = $2",
        record_type.strip().lower(),
        record_id,
    )


async def registry_list_ready_hard_purge(
    pg: PostgresClient,
    *,
    before: datetime,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    rows = await pg.fetch(
        """
        SELECT * FROM retention_soft_delete_registry
        WHERE hard_purge_after <= $1
        ORDER BY hard_purge_after
        LIMIT $2
        """,
        before,
        limit,
    )
    return [_row(dict(r)) for r in rows]


async def ndpa_fetch_kyc_including_deleted(
    pg: PostgresClient,
    customer_id: str,
) -> List[Dict[str, Any]]:
    cid = (customer_id or "").strip()
    if not cid:
        return []
    rows = await pg.fetch(
        """
        SELECT customer_id, customer_name, account_number, account_opened, customer_address,
               line_of_business, phone_number, date_of_birth, id_number, updated_at, deleted_at, anonymized_at
        FROM aml_customer_kyc
        WHERE customer_id = $1
        """,
        cid,
    )
    return [_row(dict(r)) for r in rows]


async def ndpa_registry_snapshots_for_customer(
    pg: PostgresClient,
    customer_id: str,
) -> List[Dict[str, Any]]:
    """Snapshots where JSON mentions customer_id (alerts, txns, reports)."""
    cid = (customer_id or "").strip()
    if not cid:
        return []
    rows = await pg.fetch(
        """
        SELECT id, record_type, record_id, soft_deleted_at, hard_purge_after, snapshot
        FROM retention_soft_delete_registry
        WHERE snapshot::text ILIKE $1
        ORDER BY soft_deleted_at DESC
        LIMIT 100
        """,
        f"%{cid}%",
    )
    return [_row(dict(r)) for r in rows]
