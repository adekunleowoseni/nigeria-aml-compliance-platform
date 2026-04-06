"""Statement-of-account period math and transaction lines (shared by LEA and STR packaging)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.api.v1.in_memory_stores import _TXNS
from app.services.customer_kyc_db import get_or_create_customer_kyc


def parse_iso_date(s: Optional[Any]) -> Optional[date]:
    if s is None:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except Exception:
        return None


def clamp_statement_period(
    acc_start: date,
    acc_end: date,
    p_from: Optional[date],
    p_to: Optional[date],
) -> Tuple[date, date]:
    """Clamp requested period to [acc_start, acc_end]. Raises HTTPException if inverted."""
    d_from = p_from or acc_start
    d_to = p_to or acc_end
    if d_from > d_to:
        raise HTTPException(status_code=400, detail="period_start must be on or before period_end")
    if d_from < acc_start:
        d_from = acc_start
    if d_to > acc_end:
        d_to = acc_end
    if d_from > d_to:
        d_from = d_to
    return d_from, d_to


def statement_lines_for_customer(customer_id: str, d_from: date, d_to: date) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for t in _TXNS.values():
        if t.customer_id != customer_id:
            continue
        td = t.created_at.date() if isinstance(t.created_at, datetime) else t.created_at
        if td < d_from or td > d_to:
            continue
        rows.append(
            {
                "date": td.isoformat(),
                "type": t.transaction_type,
                "amount": float(t.amount or 0.0),
                "currency": t.currency,
                "narrative": (t.narrative or "")[:240],
                "id": t.id,
            }
        )
    rows.sort(key=lambda r: r["date"])
    return rows


def format_statement_text(lines: List[Dict[str, Any]], customer_id: str, account_opened_hint: str) -> str:
    hdr = (
        f"Customer: {customer_id}\n"
        f"Account opening (KYC): {account_opened_hint}\n"
        f"Rows: {len(lines)}\n\n"
    )
    if not lines:
        return hdr + "(No transactions in the selected period.)\n"
    body = "Date       | Type        | Amount      | CCY | Transaction ID\n"
    body += "\n".join(
        f"{r['date']} | {str(r['type'])[:11]:11} | {r['amount']:11.2f} | {r['currency']} | {r['id']}"
        for r in lines
    )
    return hdr + body


def _tx_dump(t: Any) -> Dict[str, Any]:
    return t.model_dump()


async def account_context_dates_for_customer(pg: Any, customer_id: str) -> Tuple[date, date, str]:
    cid = (customer_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="customer_id is required")
    today = datetime.utcnow().date()
    txns = [t for t in _TXNS.values() if t.customer_id == cid]
    txn_dict = _tx_dump(txns[0]) if txns else {
        "created_at": datetime.utcnow(),
        "amount": 0.0,
        "transaction_type": "",
        "currency": "NGN",
        "narrative": "",
        "metadata": {},
        "customer_id": cid,
        "id": "synthetic",
    }
    kyc = await get_or_create_customer_kyc(pg, cid, txn_dict)
    opened = kyc.account_opened
    opened_s = opened.isoformat() if hasattr(opened, "isoformat") else str(opened)
    if txns:
        earliest = min(t.created_at.date() if isinstance(t.created_at, datetime) else t.created_at for t in txns)
        start = min(opened, earliest)
    else:
        start = opened
    return start, today, opened_s


def soa_period_last_twelve_months(acc_start: date, today: date) -> Tuple[date, date]:
    """Rolling ~12 months ending today, clamped to not start before account opening."""
    d_to = today
    d_from = max(acc_start, today - timedelta(days=365))
    if d_from > d_to:
        d_from = d_to
    return d_from, d_to
