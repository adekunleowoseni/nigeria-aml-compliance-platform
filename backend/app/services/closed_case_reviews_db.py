"""
Periodic review of closed cases (CBN 5.7.b.ii) — Postgres persistence.

alert_id is TEXT to match in-memory alerts. reviewer_id is analyst email.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.db.postgres_client import PostgresClient


async def ensure_closed_case_reviews_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS closed_case_review_batches (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            review_period_start DATE NOT NULL,
            review_period_end DATE NOT NULL,
            sample_type VARCHAR(20) NOT NULL DEFAULT 'RANDOM',
            reviews_created INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (review_period_start, review_period_end, sample_type)
        );
        """
    )
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS closed_case_reviews (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            alert_id TEXT NOT NULL,
            review_period_start DATE NOT NULL,
            review_period_end DATE NOT NULL,
            sample_type VARCHAR(20) NOT NULL DEFAULT 'RANDOM',
            reviewer_id TEXT,
            review_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            findings TEXT,
            pattern_identified VARCHAR(255),
            recommendation_tuning TEXT,
            requires_reopen BOOLEAN NOT NULL DEFAULT FALSE,
            reopened_alert_id TEXT,
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ccr_status_chk CHECK (
              review_status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED')
            ),
            CONSTRAINT ccr_sample_chk CHECK (
              sample_type IN ('RANDOM', 'HIGH_RISK', 'ALL')
            ),
            UNIQUE (alert_id, review_period_start, review_period_end)
        );
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ccr_status ON closed_case_reviews (review_status);
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ccr_reviewer ON closed_case_reviews (reviewer_id);
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ccr_period ON closed_case_reviews (review_period_start, review_period_end);
        """
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


async def insert_batch(
    pg: PostgresClient,
    *,
    period_start: date,
    period_end: date,
    sample_type: str,
    reviews_created: int,
) -> Optional[Dict[str, Any]]:
    try:
        r = await pg.fetchrow(
            """
            INSERT INTO closed_case_review_batches (review_period_start, review_period_end, sample_type, reviews_created)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (review_period_start, review_period_end, sample_type) DO NOTHING
            RETURNING *
            """,
            period_start,
            period_end,
            sample_type,
            reviews_created,
        )
        return _row(dict(r)) if r else None
    except Exception:
        return None


async def batch_exists(
    pg: PostgresClient,
    *,
    period_start: date,
    period_end: date,
    sample_type: str,
) -> bool:
    v = await pg.fetchval(
        """
        SELECT 1 FROM closed_case_review_batches
        WHERE review_period_start = $1 AND review_period_end = $2 AND sample_type = $3
        LIMIT 1
        """,
        period_start,
        period_end,
        sample_type,
    )
    return v is not None


async def insert_review(
    pg: PostgresClient,
    *,
    alert_id: str,
    period_start: date,
    period_end: date,
    sample_type: str,
    reviewer_id: str,
) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow(
        """
        INSERT INTO closed_case_reviews (
          alert_id, review_period_start, review_period_end, sample_type, reviewer_id, review_status
        ) VALUES ($1, $2, $3, $4, $5, 'PENDING')
        ON CONFLICT (alert_id, review_period_start, review_period_end) DO NOTHING
        RETURNING *
        """,
        alert_id,
        period_start,
        period_end,
        sample_type,
        reviewer_id,
    )
    return _row(dict(row)) if row else None


async def get_review(pg: PostgresClient, review_id: str) -> Optional[Dict[str, Any]]:
    try:
        UUID(review_id)
    except ValueError:
        return None
    row = await pg.fetchrow("SELECT * FROM closed_case_reviews WHERE id = $1::uuid", review_id)
    return _row(dict(row))


async def list_reviews(
    pg: PostgresClient,
    *,
    status: Optional[str] = None,
    reviewer_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[Dict[str, Any]], int]:
    limit = max(1, min(limit, 200))
    skip = max(0, skip)
    st = status.strip().upper() if status else None
    rev = reviewer_id.strip().lower() if reviewer_id else None

    if st and rev:
        total = await pg.fetchval(
            "SELECT COUNT(*)::int FROM closed_case_reviews WHERE review_status = $1 AND LOWER(reviewer_id) = $2",
            st,
            rev,
        )
        rows = await pg.fetch(
            """
            SELECT * FROM closed_case_reviews
            WHERE review_status = $1 AND LOWER(reviewer_id) = $2
            ORDER BY created_at DESC
            LIMIT $3 OFFSET $4
            """,
            st,
            rev,
            limit,
            skip,
        )
    elif st:
        total = await pg.fetchval(
            "SELECT COUNT(*)::int FROM closed_case_reviews WHERE review_status = $1",
            st,
        )
        rows = await pg.fetch(
            """
            SELECT * FROM closed_case_reviews WHERE review_status = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            st,
            limit,
            skip,
        )
    elif rev:
        total = await pg.fetchval(
            "SELECT COUNT(*)::int FROM closed_case_reviews WHERE LOWER(reviewer_id) = $1",
            rev,
        )
        rows = await pg.fetch(
            """
            SELECT * FROM closed_case_reviews WHERE LOWER(reviewer_id) = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            rev,
            limit,
            skip,
        )
    else:
        total = await pg.fetchval("SELECT COUNT(*)::int FROM closed_case_reviews")
        rows = await pg.fetch(
            """
            SELECT * FROM closed_case_reviews
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            skip,
        )
    return [_row(dict(r)) for r in rows], int(total or 0)


async def update_review_findings(
    pg: PostgresClient,
    review_id: str,
    *,
    findings: str,
    pattern_identified: Optional[str],
    recommendation_tuning: Optional[str],
    requires_reopen: bool,
    reopened_alert_id: Optional[str],
    review_status: str = "COMPLETED",
) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow(
        """
        UPDATE closed_case_reviews SET
          findings = $2,
          pattern_identified = $3,
          recommendation_tuning = $4,
          requires_reopen = $5,
          reopened_alert_id = COALESCE($6, reopened_alert_id),
          review_status = $7,
          reviewed_at = NOW(),
          updated_at = NOW()
        WHERE id = $1::uuid
        RETURNING *
        """,
        review_id,
        findings,
        pattern_identified,
        recommendation_tuning,
        requires_reopen,
        reopened_alert_id,
        review_status,
    )
    return _row(dict(row))


async def set_review_in_progress(pg: PostgresClient, review_id: str) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow(
        """
        UPDATE closed_case_reviews
        SET review_status = 'IN_PROGRESS', updated_at = NOW()
        WHERE id = $1::uuid AND review_status = 'PENDING'
        RETURNING *
        """,
        review_id,
    )
    return _row(dict(row))


async def aggregate_tuning_proposals(pg: PostgresClient, limit: int = 200) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 500))
    rows = await pg.fetch(
        """
        SELECT
          pattern_identified,
          COUNT(*)::int AS review_count,
          MAX(LEFT(TRIM(recommendation_tuning), 200)) AS sample_recommendations
        FROM closed_case_reviews
        WHERE review_status = 'COMPLETED'
          AND recommendation_tuning IS NOT NULL
          AND LENGTH(TRIM(recommendation_tuning)) > 0
        GROUP BY pattern_identified
        ORDER BY review_count DESC
        LIMIT $1
        """,
        limit,
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        out.append(
            {
                "pattern_identified": d.get("pattern_identified"),
                "review_count": int(d.get("review_count") or 0),
                "sample_recommendations": d.get("sample_recommendations"),
            }
        )
    return out


async def list_completed_with_recommendations(
    pg: PostgresClient,
    *,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 300))
    rows = await pg.fetch(
        """
        SELECT id, alert_id, pattern_identified, recommendation_tuning, reviewed_at, requires_reopen
        FROM closed_case_reviews
        WHERE review_status = 'COMPLETED'
          AND (recommendation_tuning IS NOT NULL AND LENGTH(TRIM(recommendation_tuning)) > 0)
        ORDER BY reviewed_at DESC NULLS LAST
        LIMIT $1
        """,
        limit,
    )
    return [_row(dict(r)) for r in rows]
