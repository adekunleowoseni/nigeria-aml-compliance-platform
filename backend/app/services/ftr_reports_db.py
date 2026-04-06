"""
Funds Transfer Report (FTR) — CBN-style cross-border / wire reporting persistence.

Uses TEXT for transaction_id and customer_id to align with in-memory transactions and aml_customer_kyc.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.db.postgres_client import PostgresClient


async def ensure_ftr_reports_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS ftr_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            report_ref VARCHAR(50) UNIQUE NOT NULL,
            transaction_id TEXT NOT NULL UNIQUE,
            customer_id TEXT NOT NULL,
            originator_name VARCHAR(200),
            originator_account VARCHAR(50),
            originator_address TEXT,
            originator_country VARCHAR(2),
            beneficiary_name VARCHAR(200),
            beneficiary_account VARCHAR(50),
            beneficiary_bank_bic VARCHAR(11),
            beneficiary_country VARCHAR(2),
            amount NUMERIC(18, 2),
            currency VARCHAR(3),
            value_date DATE,
            payment_reference VARCHAR(100),
            filing_deadline DATE,
            filing_status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
            submitted_at TIMESTAMPTZ,
            cbn_acknowledgment_ref VARCHAR(100),
            created_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ftr_reports_status_chk CHECK (
              filing_status IN ('DRAFT', 'SUBMITTED', 'ACKNOWLEDGED', 'REJECTED')
            )
        );
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ftr_reports_value_date ON ftr_reports (value_date DESC);
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ftr_reports_status ON ftr_reports (filing_status);
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ftr_reports_customer ON ftr_reports (customer_id);
        """
    )
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS ftr_auto_schedule (
            id INT PRIMARY KEY DEFAULT 1,
            enabled BOOLEAN NOT NULL DEFAULT false,
            frequency TEXT NOT NULL DEFAULT 'daily',
            threshold_ngn NUMERIC(18, 2) NOT NULL DEFAULT 1000000,
            threshold_usd NUMERIC(18, 2) NOT NULL DEFAULT 1000,
            usd_ngn_rate NUMERIC(18, 6) NOT NULL DEFAULT 1550,
            last_run_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ftr_auto_schedule_id_chk CHECK (id = 1)
        );
        """
    )
    await pg.execute(
        """
        INSERT INTO ftr_auto_schedule (id, enabled, frequency)
        VALUES (1, false, 'daily')
        ON CONFLICT (id) DO NOTHING;
        """
    )


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out


async def next_report_ref(pg: PostgresClient, *, day: date) -> str:
    prefix = day.strftime("FTR-%Y-%m-%d-")
    n = await pg.fetchval(
        """
        SELECT COUNT(*)::int FROM ftr_reports
        WHERE report_ref LIKE $1
        """,
        prefix + "%",
    )
    seq = int(n or 0) + 1
    return f"{prefix}{seq:04d}"


async def insert_ftr(
    pg: PostgresClient,
    *,
    report_ref: str,
    transaction_id: str,
    customer_id: str,
    originator_name: Optional[str],
    originator_account: Optional[str],
    originator_address: Optional[str],
    originator_country: Optional[str],
    beneficiary_name: Optional[str],
    beneficiary_account: Optional[str],
    beneficiary_bank_bic: Optional[str],
    beneficiary_country: Optional[str],
    amount: Optional[float],
    currency: Optional[str],
    value_date: date,
    payment_reference: Optional[str],
    filing_deadline: date,
    created_by: Optional[str],
) -> Dict[str, Any]:
    row = await pg.fetchrow(
        """
        INSERT INTO ftr_reports (
          report_ref, transaction_id, customer_id,
          originator_name, originator_account, originator_address, originator_country,
          beneficiary_name, beneficiary_account, beneficiary_bank_bic, beneficiary_country,
          amount, currency, value_date, payment_reference, filing_deadline, filing_status, created_by
        ) VALUES (
          $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, 'DRAFT', $17
        )
        RETURNING *
        """,
        report_ref,
        transaction_id,
        customer_id,
        originator_name,
        originator_account,
        originator_address,
        originator_country,
        beneficiary_name,
        beneficiary_account,
        beneficiary_bank_bic,
        beneficiary_country,
        amount,
        currency,
        value_date,
        payment_reference,
        filing_deadline,
        created_by,
    )
    return _row_to_dict(row or {})


async def get_ftr_by_id(pg: PostgresClient, ftr_id: str) -> Optional[Dict[str, Any]]:
    try:
        UUID(ftr_id)
    except ValueError:
        return None
    row = await pg.fetchrow("SELECT * FROM ftr_reports WHERE id = $1::uuid", ftr_id)
    return _row_to_dict(dict(row)) if row else None


async def get_ftr_by_transaction(pg: PostgresClient, transaction_id: str) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow("SELECT * FROM ftr_reports WHERE transaction_id = $1", transaction_id)
    return _row_to_dict(dict(row)) if row else None


async def list_ftrs(
    pg: PostgresClient,
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[List[Dict[str, Any]], int]:
    limit = max(1, min(limit, 200))
    skip = max(0, skip)
    st = status.strip().upper() if status else None

    if from_date is not None and to_date is not None and st:
        total = await pg.fetchval(
            "SELECT COUNT(*)::int FROM ftr_reports WHERE value_date >= $1 AND value_date <= $2 AND filing_status = $3",
            from_date,
            to_date,
            st,
        )
        rows = await pg.fetch(
            """
            SELECT * FROM ftr_reports
            WHERE value_date >= $1 AND value_date <= $2 AND filing_status = $3
            ORDER BY value_date DESC NULLS LAST, created_at DESC
            LIMIT $4 OFFSET $5
            """,
            from_date,
            to_date,
            st,
            limit,
            skip,
        )
    elif from_date is not None and to_date is not None:
        total = await pg.fetchval(
            "SELECT COUNT(*)::int FROM ftr_reports WHERE value_date >= $1 AND value_date <= $2",
            from_date,
            to_date,
        )
        rows = await pg.fetch(
            """
            SELECT * FROM ftr_reports
            WHERE value_date >= $1 AND value_date <= $2
            ORDER BY value_date DESC NULLS LAST, created_at DESC
            LIMIT $3 OFFSET $4
            """,
            from_date,
            to_date,
            limit,
            skip,
        )
    elif from_date is not None and st:
        total = await pg.fetchval(
            "SELECT COUNT(*)::int FROM ftr_reports WHERE value_date >= $1 AND filing_status = $2",
            from_date,
            st,
        )
        rows = await pg.fetch(
            """
            SELECT * FROM ftr_reports
            WHERE value_date >= $1 AND filing_status = $2
            ORDER BY value_date DESC NULLS LAST, created_at DESC
            LIMIT $3 OFFSET $4
            """,
            from_date,
            st,
            limit,
            skip,
        )
    elif to_date is not None and st:
        total = await pg.fetchval(
            "SELECT COUNT(*)::int FROM ftr_reports WHERE value_date <= $1 AND filing_status = $2",
            to_date,
            st,
        )
        rows = await pg.fetch(
            """
            SELECT * FROM ftr_reports
            WHERE value_date <= $1 AND filing_status = $2
            ORDER BY value_date DESC NULLS LAST, created_at DESC
            LIMIT $3 OFFSET $4
            """,
            to_date,
            st,
            limit,
            skip,
        )
    elif from_date is not None:
        total = await pg.fetchval("SELECT COUNT(*)::int FROM ftr_reports WHERE value_date >= $1", from_date)
        rows = await pg.fetch(
            """
            SELECT * FROM ftr_reports WHERE value_date >= $1
            ORDER BY value_date DESC NULLS LAST, created_at DESC
            LIMIT $2 OFFSET $3
            """,
            from_date,
            limit,
            skip,
        )
    elif to_date is not None:
        total = await pg.fetchval("SELECT COUNT(*)::int FROM ftr_reports WHERE value_date <= $1", to_date)
        rows = await pg.fetch(
            """
            SELECT * FROM ftr_reports WHERE value_date <= $1
            ORDER BY value_date DESC NULLS LAST, created_at DESC
            LIMIT $2 OFFSET $3
            """,
            to_date,
            limit,
            skip,
        )
    elif st:
        total = await pg.fetchval("SELECT COUNT(*)::int FROM ftr_reports WHERE filing_status = $1", st)
        rows = await pg.fetch(
            """
            SELECT * FROM ftr_reports WHERE filing_status = $1
            ORDER BY value_date DESC NULLS LAST, created_at DESC
            LIMIT $2 OFFSET $3
            """,
            st,
            limit,
            skip,
        )
    else:
        total = await pg.fetchval("SELECT COUNT(*)::int FROM ftr_reports")
        rows = await pg.fetch(
            """
            SELECT * FROM ftr_reports
            ORDER BY value_date DESC NULLS LAST, created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            skip,
        )
    return [_row_to_dict(dict(r)) for r in rows], int(total or 0)


async def update_ftr_draft(
    pg: PostgresClient,
    ftr_id: str,
    fields: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    allowed = {
        "originator_name",
        "originator_account",
        "originator_address",
        "originator_country",
        "beneficiary_name",
        "beneficiary_account",
        "beneficiary_bank_bic",
        "beneficiary_country",
        "amount",
        "currency",
        "value_date",
        "payment_reference",
    }
    sets: List[str] = []
    args: List[Any] = []
    i = 1
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k == "value_date" and isinstance(v, str):
            try:
                v = date.fromisoformat(v[:10])
            except ValueError:
                continue
        sets.append(f"{k} = ${i}")
        args.append(v)
        i += 1
    if not sets:
        row = await pg.fetchrow("SELECT * FROM ftr_reports WHERE id = $1::uuid AND filing_status = 'DRAFT'", ftr_id)
        return _row_to_dict(dict(row)) if row else None
    sets.append(f"updated_at = ${i}")
    args.append(datetime.now(timezone.utc))
    i += 1
    args.append(ftr_id)
    q = f"""
    UPDATE ftr_reports SET {", ".join(sets)}
    WHERE id = ${i}::uuid AND filing_status = 'DRAFT'
    RETURNING *
    """
    row = await pg.fetchrow(q, *args)
    return _row_to_dict(dict(row)) if row else None


async def mark_ftr_submitted(
    pg: PostgresClient,
    ftr_id: str,
    *,
    cbn_ack: Optional[str],
) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow(
        """
        UPDATE ftr_reports
        SET filing_status = 'SUBMITTED',
            submitted_at = NOW(),
            cbn_acknowledgment_ref = COALESCE($2, cbn_acknowledgment_ref),
            updated_at = NOW()
        WHERE id = $1::uuid AND filing_status = 'DRAFT'
        RETURNING *
        """,
        ftr_id,
        cbn_ack,
    )
    return _row_to_dict(dict(row)) if row else None


async def get_schedule(pg: PostgresClient) -> Dict[str, Any]:
    row = await pg.fetchrow("SELECT * FROM ftr_auto_schedule WHERE id = 1")
    if not row:
        return {}
    return _row_to_dict(dict(row))


async def upsert_schedule(
    pg: PostgresClient,
    *,
    enabled: Optional[bool] = None,
    frequency: Optional[str] = None,
    threshold_ngn: Optional[float] = None,
    threshold_usd: Optional[float] = None,
    usd_ngn_rate: Optional[float] = None,
) -> Dict[str, Any]:
    cur = await get_schedule(pg)
    en = enabled if enabled is not None else bool(cur.get("enabled"))
    fr = (frequency or cur.get("frequency") or "daily").strip().lower()
    tn = float(threshold_ngn) if threshold_ngn is not None else float(cur.get("threshold_ngn") or 1_000_000)
    tu = float(threshold_usd) if threshold_usd is not None else float(cur.get("threshold_usd") or 1000)
    ur = float(usd_ngn_rate) if usd_ngn_rate is not None else float(cur.get("usd_ngn_rate") or 1550)
    await pg.execute(
        """
        INSERT INTO ftr_auto_schedule (id, enabled, frequency, threshold_ngn, threshold_usd, usd_ngn_rate, updated_at)
        VALUES (1, $1, $2, $3, $4, $5, NOW())
        ON CONFLICT (id) DO UPDATE SET
          enabled = EXCLUDED.enabled,
          frequency = EXCLUDED.frequency,
          threshold_ngn = EXCLUDED.threshold_ngn,
          threshold_usd = EXCLUDED.threshold_usd,
          usd_ngn_rate = EXCLUDED.usd_ngn_rate,
          updated_at = NOW();
        """,
        en,
        fr,
        tn,
        tu,
        ur,
    )
    return await get_schedule(pg)


async def touch_schedule_last_run(pg: PostgresClient) -> None:
    await pg.execute("UPDATE ftr_auto_schedule SET last_run_at = NOW(), updated_at = NOW() WHERE id = 1")
