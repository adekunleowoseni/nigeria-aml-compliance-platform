from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.db.postgres_client import PostgresClient
from app.services.str_word_generator import (
    CustomerKyc,
    build_customer_kyc,
    infer_line_of_business_from_customer_id,
    infer_line_of_business_from_txn,
)

# Fallback when Postgres insert fails (e.g. readonly / transient errors)
_MEMORY_KYC: Dict[str, CustomerKyc] = {}

# When merging DB with demo txn/memory sources, cap how many Postgres rows we pull (demo-scale).
_DEMO_MERGE_PG_CAP = 5000


def _needle_matches_customer_row(
    needle_lower: str, customer_id: str, name: str, account_number: str, id_number: Optional[str]
) -> bool:
    if not needle_lower:
        return True
    blob = f"{customer_id} {name} {account_number} {id_number or ''}".lower()
    return needle_lower in blob


def clear_memory_kyc() -> None:
    _MEMORY_KYC.clear()


async def ensure_aml_customer_kyc_table(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS aml_customer_kyc (
            customer_id TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            account_number TEXT NOT NULL,
            account_opened DATE NOT NULL,
            customer_address TEXT NOT NULL,
            line_of_business TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            date_of_birth DATE NOT NULL,
            id_number TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    for stmt in (
        "ALTER TABLE aml_customer_kyc ADD COLUMN IF NOT EXISTS customer_segment TEXT NOT NULL DEFAULT 'individual'",
        "ALTER TABLE aml_customer_kyc ADD COLUMN IF NOT EXISTS expected_annual_turnover DOUBLE PRECISION",
        "ALTER TABLE aml_customer_kyc ADD COLUMN IF NOT EXISTS customer_remarks TEXT NOT NULL DEFAULT ''",
    ):
        try:
            await pg.execute(stmt)
        except Exception:
            pass


def _as_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
        except Exception:
            return date(1977, 9, 5)
    return date(1977, 9, 5)


def _row_to_customer(row: Dict[str, Any]) -> CustomerKyc:
    exp = row.get("expected_annual_turnover")
    try:
        exp_f = float(exp) if exp is not None else None
    except (TypeError, ValueError):
        exp_f = None
    lob_raw = str(row.get("line_of_business") or "").strip()
    lob = lob_raw or infer_line_of_business_from_customer_id(str(row.get("customer_id") or "")) or "Occupation not stated"
    return CustomerKyc(
        customer_name=str(row["customer_name"]),
        account_number=str(row["account_number"]),
        account_opened=_as_date(row["account_opened"]),
        customer_address=str(row["customer_address"]),
        line_of_business=lob,
        phone_number=str(row["phone_number"]),
        date_of_birth=_as_date(row["date_of_birth"]),
        id_number=str(row["id_number"]),
        customer_segment=str(row.get("customer_segment") or "individual").strip() or "individual",
        expected_annual_turnover=exp_f,
        customer_remarks=str(row.get("customer_remarks") or ""),
    )


async def get_or_create_customer_kyc(
    pg: Optional[PostgresClient],
    customer_id: str,
    txn: Dict[str, Any],
) -> CustomerKyc:
    """
    Load KYC from Postgres when present; otherwise generate deterministic demo data,
    persist it, and return it (in-memory fallback if DB write fails).
    """
    cid = (customer_id or "").strip() or "unknown"
    inferred = infer_line_of_business_from_txn(txn)

    if cid in _MEMORY_KYC:
        return _MEMORY_KYC[cid]

    if pg is not None:
        try:
            row = await pg.fetchrow(
                "SELECT customer_id, customer_name, account_number, account_opened, customer_address, "
                "line_of_business, phone_number, date_of_birth, id_number "
                "FROM aml_customer_kyc WHERE customer_id = $1 AND deleted_at IS NULL",
                cid,
            )
            if row:
                kyc = _row_to_customer(row)
                _MEMORY_KYC[cid] = kyc
                return kyc
        except Exception:
            pass

    synthetic = build_customer_kyc(cid, inferred_lob=inferred, use_placeholders=False)

    if pg is not None:
        try:
            await pg.execute(
                """
                INSERT INTO aml_customer_kyc (
                    customer_id, customer_name, account_number, account_opened,
                    customer_address, line_of_business, phone_number, date_of_birth, id_number,
                    customer_segment, expected_annual_turnover, customer_remarks
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (customer_id) DO UPDATE SET
                    customer_name = EXCLUDED.customer_name,
                    account_number = EXCLUDED.account_number,
                    account_opened = EXCLUDED.account_opened,
                    customer_address = EXCLUDED.customer_address,
                    line_of_business = EXCLUDED.line_of_business,
                    phone_number = EXCLUDED.phone_number,
                    date_of_birth = EXCLUDED.date_of_birth,
                    id_number = EXCLUDED.id_number,
                    customer_segment = EXCLUDED.customer_segment,
                    expected_annual_turnover = EXCLUDED.expected_annual_turnover,
                    customer_remarks = EXCLUDED.customer_remarks,
                    deleted_at = NULL,
                    updated_at = NOW()
                """,
                cid,
                synthetic.customer_name,
                synthetic.account_number,
                synthetic.account_opened,
                synthetic.customer_address,
                synthetic.line_of_business,
                synthetic.phone_number,
                synthetic.date_of_birth,
                synthetic.id_number,
                synthetic.customer_segment,
                synthetic.expected_annual_turnover,
                synthetic.customer_remarks or "",
            )
        except Exception:
            _MEMORY_KYC[cid] = synthetic
            return synthetic

    _MEMORY_KYC[cid] = synthetic
    return synthetic


async def list_bvn_linked_accounts(
    pg: Optional[PostgresClient],
    id_number: str,
    *,
    primary_customer_id: str,
) -> List[Dict[str, Any]]:
    """All accounts (rows) sharing the same BVN / national ID in aml_customer_kyc."""
    bvn = (id_number or "").strip()
    out: List[Dict[str, Any]] = []
    if pg is not None and bvn:
        try:
            rows = await pg.fetch(
                "SELECT customer_id, account_number, customer_name FROM aml_customer_kyc "
                "WHERE id_number = $1 AND deleted_at IS NULL ORDER BY customer_id",
                bvn,
            )
            for r in rows:
                out.append(
                    {
                        "customer_id": r["customer_id"],
                        "account_number": r["account_number"],
                        "customer_name": r["customer_name"],
                        "bvn": bvn,
                        "source": "database",
                    }
                )
        except Exception:
            pass
    if not out and primary_customer_id in _MEMORY_KYC:
        kyc = _MEMORY_KYC[primary_customer_id]
        out.append(
            {
                "customer_id": primary_customer_id,
                "account_number": kyc.account_number,
                "customer_name": kyc.customer_name,
                "bvn": kyc.id_number,
                "source": "memory",
            }
        )
    return out


async def fetch_customer_kyc_any(pg: Optional[PostgresClient], customer_id: str) -> Optional[CustomerKyc]:
    """Return KYC from Postgres if present, else from in-memory fallback cache."""
    cid = (customer_id or "").strip()
    if not cid:
        return None
    if pg is not None:
        try:
            row = await pg.fetchrow(
                "SELECT customer_id, customer_name, account_number, account_opened, customer_address, "
                "line_of_business, phone_number, date_of_birth, id_number "
                "FROM aml_customer_kyc WHERE customer_id = $1 AND deleted_at IS NULL",
                cid,
            )
            if row:
                return _row_to_customer(row)
        except Exception:
            pass
    return _MEMORY_KYC.get(cid)


async def upsert_customer_kyc_explicit(
    pg: Optional[PostgresClient],
    customer_id: str,
    *,
    customer_name: str,
    account_number: str,
    account_opened: date,
    customer_address: str,
    line_of_business: str,
    phone_number: str,
    date_of_birth: date,
    id_number: str,
) -> CustomerKyc:
    """Persist officer-entered KYC; refreshes memory cache for this customer."""
    cid = (customer_id or "").strip() or "unknown"
    kyc = CustomerKyc(
        customer_name=(customer_name or "").strip() or "Unknown",
        account_number=(account_number or "").strip() or "—",
        account_opened=account_opened,
        customer_address=(customer_address or "").strip() or "—",
        line_of_business=(line_of_business or "").strip() or "Occupation not stated",
        phone_number=(phone_number or "").strip() or "—",
        date_of_birth=date_of_birth,
        id_number=(id_number or "").strip() or "—",
    )
    if pg is not None:
        try:
            await pg.execute(
                """
                INSERT INTO aml_customer_kyc (
                    customer_id, customer_name, account_number, account_opened,
                    customer_address, line_of_business, phone_number, date_of_birth, id_number
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (customer_id) DO UPDATE SET
                    customer_name = EXCLUDED.customer_name,
                    account_number = EXCLUDED.account_number,
                    account_opened = EXCLUDED.account_opened,
                    customer_address = EXCLUDED.customer_address,
                    line_of_business = EXCLUDED.line_of_business,
                    phone_number = EXCLUDED.phone_number,
                    date_of_birth = EXCLUDED.date_of_birth,
                    id_number = EXCLUDED.id_number,
                    deleted_at = NULL,
                    updated_at = NOW()
                """,
                cid,
                kyc.customer_name,
                kyc.account_number,
                kyc.account_opened,
                kyc.customer_address,
                kyc.line_of_business,
                kyc.phone_number,
                kyc.date_of_birth,
                kyc.id_number,
            )
        except Exception:
            _MEMORY_KYC[cid] = kyc
            return kyc
    else:
        _MEMORY_KYC[cid] = kyc
        return kyc
    _MEMORY_KYC[cid] = kyc
    return kyc


async def list_customers_kyc(
    pg: Optional[PostgresClient],
    *,
    limit: int = 50,
    offset: int = 0,
    q: Optional[str] = None,
    merge_demo_sources: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """List customer rows for onboarding UI (Postgres; falls back to in-memory cache if no pool)."""
    needle = (q or "").strip().lower()
    needle_raw = (q or "").strip()

    if pg is None:
        if merge_demo_sources:
            from app.api.v1.in_memory_stores import _TXNS

            by_id: dict[str, dict[str, Any]] = {}
            for cid, kyc in _MEMORY_KYC.items():
                if not _needle_matches_customer_row(
                    needle, cid, kyc.customer_name or "", kyc.account_number or "", kyc.id_number
                ):
                    continue
                by_id[cid] = {
                    "customer_id": cid,
                    "customer_name": kyc.customer_name,
                    "account_number": kyc.account_number,
                    "account_opened": kyc.account_opened,
                    "id_number": kyc.id_number,
                    "updated_at": None,
                }
            for t in _TXNS.values():
                cid = (t.customer_id or "").strip()
                if not cid or cid in by_id:
                    continue
                td = t.model_dump()
                syn = build_customer_kyc(
                    cid, inferred_lob=infer_line_of_business_from_txn(td), use_placeholders=False
                )
                if not _needle_matches_customer_row(
                    needle, cid, syn.customer_name, syn.account_number, syn.id_number
                ):
                    continue
                by_id[cid] = {
                    "customer_id": cid,
                    "customer_name": syn.customer_name,
                    "account_number": syn.account_number,
                    "account_opened": syn.account_opened,
                    "id_number": syn.id_number,
                    "updated_at": None,
                }
            merged = sorted(by_id.values(), key=lambda r: (str(r["customer_name"] or "").lower(), r["customer_id"]))
            total = len(merged)
            return merged[offset : offset + limit], total

        mem_rows: list[dict[str, Any]] = []
        for cid, kyc in sorted(_MEMORY_KYC.items(), key=lambda x: x[0]):
            if needle and needle not in cid.lower() and needle not in (kyc.customer_name or "").lower():
                continue
            mem_rows.append(
                {
                    "customer_id": cid,
                    "customer_name": kyc.customer_name,
                    "account_number": kyc.account_number,
                    "account_opened": kyc.account_opened,
                    "id_number": kyc.id_number,
                    "updated_at": None,
                }
            )
        total = len(mem_rows)
        return mem_rows[offset : offset + limit], total

    if merge_demo_sources:
        from app.api.v1.in_memory_stores import _TXNS

        by_id_m: dict[str, dict[str, Any]] = {}
        try:
            if needle_raw:
                pat = f"%{needle_raw}%"
                db_rows = await pg.fetch(
                    "SELECT customer_id, customer_name, account_number, account_opened, id_number, updated_at "
                    "FROM aml_customer_kyc WHERE deleted_at IS NULL AND ("
                    "customer_id ILIKE $1 OR customer_name ILIKE $1 OR account_number ILIKE $1 OR id_number ILIKE $1) "
                    "ORDER BY updated_at DESC NULLS LAST LIMIT $2",
                    pat,
                    _DEMO_MERGE_PG_CAP,
                )
            else:
                db_rows = await pg.fetch(
                    "SELECT customer_id, customer_name, account_number, account_opened, id_number, updated_at "
                    "FROM aml_customer_kyc WHERE deleted_at IS NULL "
                    "ORDER BY updated_at DESC NULLS LAST LIMIT $1",
                    _DEMO_MERGE_PG_CAP,
                )
            for r in db_rows:
                by_id_m[str(r["customer_id"])] = dict(r)
        except Exception:
            pass

        for cid, kyc in _MEMORY_KYC.items():
            if cid in by_id_m:
                continue
            if not _needle_matches_customer_row(
                needle, cid, kyc.customer_name or "", kyc.account_number or "", kyc.id_number
            ):
                continue
            by_id_m[cid] = {
                "customer_id": cid,
                "customer_name": kyc.customer_name,
                "account_number": kyc.account_number,
                "account_opened": kyc.account_opened,
                "id_number": kyc.id_number,
                "updated_at": None,
            }

        for t in _TXNS.values():
            cid = (t.customer_id or "").strip()
            if not cid or cid in by_id_m:
                continue
            td = t.model_dump()
            syn = build_customer_kyc(
                cid, inferred_lob=infer_line_of_business_from_txn(td), use_placeholders=False
            )
            if not _needle_matches_customer_row(
                needle, cid, syn.customer_name, syn.account_number, syn.id_number
            ):
                continue
            by_id_m[cid] = {
                "customer_id": cid,
                "customer_name": syn.customer_name,
                "account_number": syn.account_number,
                "account_opened": syn.account_opened,
                "id_number": syn.id_number,
                "updated_at": None,
            }

        merged_pg = sorted(
            by_id_m.values(), key=lambda r: (str(r.get("customer_name") or "").lower(), r["customer_id"])
        )
        total_m = len(merged_pg)
        return merged_pg[offset : offset + limit], total_m

    try:
        if needle_raw:
            pat = f"%{needle_raw}%"
            total = int(
                await pg.fetchval(
                    "SELECT COUNT(*) FROM aml_customer_kyc WHERE deleted_at IS NULL AND ("
                    "customer_id ILIKE $1 OR customer_name ILIKE $1 OR account_number ILIKE $1 OR id_number ILIKE $1)",
                    pat,
                )
            )
            rows = await pg.fetch(
                "SELECT customer_id, customer_name, account_number, account_opened, id_number, updated_at "
                "FROM aml_customer_kyc WHERE deleted_at IS NULL AND ("
                "customer_id ILIKE $1 OR customer_name ILIKE $1 OR account_number ILIKE $1 OR id_number ILIKE $1) "
                "ORDER BY updated_at DESC NULLS LAST LIMIT $2 OFFSET $3",
                pat,
                limit,
                offset,
            )
        else:
            total = int(await pg.fetchval("SELECT COUNT(*) FROM aml_customer_kyc WHERE deleted_at IS NULL"))
            rows = await pg.fetch(
                "SELECT customer_id, customer_name, account_number, account_opened, id_number, updated_at "
                "FROM aml_customer_kyc WHERE deleted_at IS NULL "
                "ORDER BY updated_at DESC NULLS LAST LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
        return rows, total
    except Exception:
        return [], 0
