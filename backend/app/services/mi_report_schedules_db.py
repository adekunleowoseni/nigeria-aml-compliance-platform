"""Persist MI report email schedules (cron + recipients); pause/resume for admin."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.db.postgres_client import PostgresClient

VALID_REPORT_TYPES = frozenset({"board_aml_pack", "eco_dashboard", "management_exceptions"})


async def ensure_mi_schedule_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS mi_report_schedules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            report_type VARCHAR(64) NOT NULL,
            cron_expression VARCHAR(128) NOT NULL,
            recipients JSONB NOT NULL DEFAULT '[]'::jsonb,
            is_paused BOOLEAN NOT NULL DEFAULT FALSE,
            last_fired_at TIMESTAMPTZ,
            updated_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT mi_report_schedules_type_chk CHECK (
              report_type IN ('board_aml_pack', 'eco_dashboard', 'management_exceptions')
            )
        );
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mi_report_schedules_type ON mi_report_schedules (report_type);
        """
    )


def _row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, UUID):
            out[k] = str(v)
    return out


async def insert_schedule(
    pg: PostgresClient,
    *,
    report_type: str,
    cron_expression: str,
    recipients: List[str],
    is_paused: bool,
    updated_by: Optional[str],
) -> Dict[str, Any]:
    rt = report_type.strip().lower()
    if rt not in VALID_REPORT_TYPES:
        raise ValueError("invalid report_type")
    r = await pg.fetchrow(
        """
        INSERT INTO mi_report_schedules (
          report_type, cron_expression, recipients, is_paused, updated_by, updated_at, last_fired_at
        ) VALUES ($1, $2, $3::jsonb, $4, $5, NOW(), NOW())
        RETURNING *
        """,
        rt,
        cron_expression.strip(),
        recipients,
        bool(is_paused),
        updated_by,
    )
    return _row(dict(r)) if r else {}


async def list_schedules(pg: PostgresClient) -> List[Dict[str, Any]]:
    rows = await pg.fetch("SELECT * FROM mi_report_schedules ORDER BY report_type, created_at")
    return [_row(dict(r)) for r in rows]


async def get_schedule(pg: PostgresClient, schedule_id: str) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow("SELECT * FROM mi_report_schedules WHERE id = $1::uuid", schedule_id)
    return _row(dict(row)) if row else None


async def set_paused(pg: PostgresClient, schedule_id: str, is_paused: bool, updated_by: Optional[str]) -> bool:
    r = await pg.execute(
        """
        UPDATE mi_report_schedules SET is_paused = $2, updated_by = $3, updated_at = NOW()
        WHERE id = $1::uuid
        """,
        schedule_id,
        bool(is_paused),
        updated_by,
    )
    return str(r).endswith("UPDATE 1")


async def touch_fired(pg: PostgresClient, schedule_id: str) -> None:
    await pg.execute(
        "UPDATE mi_report_schedules SET last_fired_at = NOW(), updated_at = NOW() WHERE id = $1::uuid",
        schedule_id,
    )
