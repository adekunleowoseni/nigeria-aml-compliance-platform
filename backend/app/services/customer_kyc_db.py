from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from app.db.postgres_client import PostgresClient
from app.services.str_word_generator import CustomerKyc, build_customer_kyc, infer_line_of_business_from_txn

# Fallback when Postgres insert fails (e.g. readonly / transient errors)
_MEMORY_KYC: Dict[str, CustomerKyc] = {}


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
    return CustomerKyc(
        customer_name=str(row["customer_name"]),
        account_number=str(row["account_number"]),
        account_opened=_as_date(row["account_opened"]),
        customer_address=str(row["customer_address"]),
        line_of_business=str(row["line_of_business"]),
        phone_number=str(row["phone_number"]),
        date_of_birth=_as_date(row["date_of_birth"]),
        id_number=str(row["id_number"]),
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
                "FROM aml_customer_kyc WHERE customer_id = $1",
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
            )
        except Exception:
            _MEMORY_KYC[cid] = synthetic
            return synthetic

    _MEMORY_KYC[cid] = synthetic
    return synthetic
