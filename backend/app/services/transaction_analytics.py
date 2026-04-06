from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


def _txn_ts(txn: Dict[str, Any]) -> datetime:
    ts = txn.get("timestamp") or txn.get("created_at")
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    if isinstance(ts, str):
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return t.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _is_inflow(txn: Dict[str, Any]) -> bool:
    tx_type = str(txn.get("transaction_type") or "").lower()
    return any(x in tx_type for x in ("in", "deposit", "salary", "credit", "settlement", "wire_in")) or (
        "out" not in tx_type and "transfer" in tx_type
    )


def _is_outflow(txn: Dict[str, Any]) -> bool:
    tx_type = str(txn.get("transaction_type") or "").lower()
    return "out" in tx_type or tx_type in ("transfer_out", "withdrawal", "debit")


def ytd_calendar_year_inflow_ngn(
    customer_id: str,
    baseline_txns: List[Dict[str, Any]],
    txn: Dict[str, Any],
) -> float:
    """
    Sum NGN inflows for ``customer_id`` in the same calendar year as ``txn``,
    including the current transaction (baseline is strictly prior events).
    """
    y = _txn_ts(txn).year
    total = 0.0
    cid = str(customer_id)
    for t in baseline_txns:
        if str(t.get("customer_id") or "") != cid:
            continue
        if _txn_ts(t).year != y:
            continue
        if not _is_inflow(t):
            continue
        if str(t.get("currency") or "NGN").upper() != "NGN":
            continue
        total += float(t.get("amount") or 0.0)
    if (
        str(txn.get("customer_id") or "") == cid
        and _txn_ts(txn).year == y
        and _is_inflow(txn)
        and str(txn.get("currency") or "NGN").upper() == "NGN"
    ):
        total += float(txn.get("amount") or 0.0)
    return total


@dataclass
class FlowMetrics:
    """Rolling windows for AML narratives (NFIU-oriented)."""
    window_24h_start: str
    window_24h_end: str
    ytd_12m_start: str
    ytd_12m_end: str
    txn_count_24h: int = 0
    inflow_24h: float = 0.0
    outflow_24h: float = 0.0
    inflow_12m: float = 0.0
    outflow_12m: float = 0.0
    lifetime_start: Optional[str] = None
    lifetime_inflow: float = 0.0
    lifetime_outflow: float = 0.0
    lifetime_txn_count: int = 0
    account_age_days: Optional[int] = None


@dataclass
class CounterpartyFlow:
    direction: str  # "inbound" | "outbound"
    counterparty_id: str
    counterparty_name: Optional[str]
    bank_or_institution: Optional[str]
    total_amount: float
    txn_count: int


@dataclass
class FundsUtilization:
    """Post-flag movement heuristic (not ledger settlement)."""
    description: str
    funds_utilized: Optional[bool]  # True if meaningful outflows after flagged txn
    subsequent_outflow_total: float = 0.0
    days_observed: int = 0


def compute_flow_metrics(
    customer_id: str,
    all_txns: List[Dict[str, Any]],
    *,
    as_of: Optional[datetime] = None,
) -> FlowMetrics:
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start_24h = now - timedelta(hours=24)
    start_12m = now - timedelta(days=365)

    cust_txns = [t for t in all_txns if str(t.get("customer_id") or "") == customer_id]
    cust_txns.sort(key=_txn_ts)

    m = FlowMetrics(
        window_24h_start=start_24h.isoformat(),
        window_24h_end=now.isoformat(),
        ytd_12m_start=start_12m.isoformat(),
        ytd_12m_end=now.isoformat(),
    )

    first_ts: Optional[datetime] = None
    for t in cust_txns:
        ts = _txn_ts(t)
        if first_ts is None:
            first_ts = ts
        amt = float(t.get("amount") or 0.0)
        m.lifetime_txn_count += 1
        if _is_inflow(t):
            m.lifetime_inflow += amt
        elif _is_outflow(t):
            m.lifetime_outflow += amt
        else:
            m.lifetime_inflow += amt

        if ts >= start_24h:
            m.txn_count_24h += 1
            if _is_inflow(t):
                m.inflow_24h += amt
            elif _is_outflow(t):
                m.outflow_24h += amt
            else:
                m.inflow_24h += amt

        if ts >= start_12m:
            if _is_inflow(t):
                m.inflow_12m += amt
            elif _is_outflow(t):
                m.outflow_12m += amt
            else:
                m.inflow_12m += amt

    if first_ts:
        m.lifetime_start = first_ts.isoformat()
        m.account_age_days = max(0, (now - first_ts).days)
    return m


def aggregate_counterparty_flows(
    customer_id: str,
    all_txns: List[Dict[str, Any]],
    *,
    top_n: int = 8,
) -> Tuple[List[CounterpartyFlow], List[CounterpartyFlow]]:
    inbound: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"amt": 0.0, "n": 0, "name": None, "bank": None})
    outbound: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"amt": 0.0, "n": 0, "name": None, "bank": None})

    for t in all_txns:
        if str(t.get("customer_id") or "") != customer_id:
            continue
        meta = t.get("metadata") or {}
        cpid = str(t.get("counterparty_id") or "").strip()
        cpname = t.get("counterparty_name")
        bank = None
        if isinstance(meta, dict):
            cpid = cpid or str(meta.get("counterparty_id") or "").strip()
            cpname = cpname or meta.get("counterparty_name")
            bank = meta.get("sender_bank") or meta.get("bank") or meta.get("institution")
        if not cpid:
            cpid = "UNKNOWN"
        amt = float(t.get("amount") or 0.0)
        if _is_outflow(t):
            bucket = outbound[cpid]
            bucket["amt"] += amt
            bucket["n"] += 1
            bucket["name"] = bucket["name"] or cpname
            bucket["bank"] = bucket["bank"] or bank
        else:
            bucket = inbound[cpid]
            bucket["amt"] += amt
            bucket["n"] += 1
            bucket["name"] = bucket["name"] or cpname
            bucket["bank"] = bucket["bank"] or bank

    def to_flows(d: Dict[str, Dict[str, Any]], direction: str) -> List[CounterpartyFlow]:
        rows = [
            CounterpartyFlow(
                direction=direction,
                counterparty_id=k,
                counterparty_name=v.get("name"),
                bank_or_institution=v.get("bank"),
                total_amount=v["amt"],
                txn_count=v["n"],
            )
            for k, v in d.items()
        ]
        rows.sort(key=lambda x: x.total_amount, reverse=True)
        return rows[:top_n]

    return to_flows(inbound, "inbound"), to_flows(outbound, "outbound")


def assess_funds_utilization(
    flagged_txn: Dict[str, Any],
    customer_txns: List[Dict[str, Any]],
    *,
    lookforward_days: int = 90,
) -> FundsUtilization:
    """Heuristic: meaningful outbound activity after the flagged event suggests utilization."""
    ts0 = _txn_ts(flagged_txn)
    end = ts0 + timedelta(days=lookforward_days)
    fid = str(flagged_txn.get("id") or "")

    subsequent_out = 0.0
    days_span = 0
    for t in customer_txns:
        if str(t.get("id") or "") == fid:
            continue
        ts = _txn_ts(t)
        if ts <= ts0 or ts > end:
            continue
        if _is_outflow(t):
            subsequent_out += float(t.get("amount") or 0.0)
            days_span = max(days_span, (ts - ts0).days)

    threshold = max(50_000.0, float(flagged_txn.get("amount") or 0) * 0.05)
    utilized = subsequent_out >= threshold if float(flagged_txn.get("amount") or 0) > 0 else None

    if subsequent_out < 1:
        desc = (
            "No material outbound movement observed in the reviewed window after this transaction; "
            "funds may remain in the account pending further monitoring."
        )
    elif utilized:
        desc = (
            f"Subsequent outflows of approximately ₦{subsequent_out:,.0f} were observed within {lookforward_days} days "
            "after the flagged event, indicating funds may have been utilised or layered."
        )
    else:
        desc = (
            f"Limited subsequent outflows (₦{subsequent_out:,.0f}) relative to the flagged amount; "
            "utilisation status remains inconclusive pending full ledger review."
        )

    return FundsUtilization(
        description=desc,
        funds_utilized=utilized,
        subsequent_outflow_total=subsequent_out,
        days_observed=days_span,
    )


def adverse_media_placeholder(customer_name: str, sanctions_hits: int) -> str:
    if sanctions_hits > 0:
        return (
            f"Sanctions / watchlist screening returned {sanctions_hits} potential match(es) for related names; "
            "independent adverse media review is required per internal policy."
        )
    return (
        f"No adverse media hits were returned from automated sanctions screening for “{customer_name}” at the time "
        "of this report. Enhanced open-source media review is recommended for high-risk cases."
    )
