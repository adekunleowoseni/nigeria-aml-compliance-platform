from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.db.postgres_client import PostgresClient
from app.models.alert import AlertResponse
from app.services.customer_kyc_db import get_or_create_customer_kyc, list_bvn_linked_accounts
from app.services.sanctions_screening import screen_name_opensanctions
from app.services.transaction_analytics import (
    adverse_media_placeholder,
    aggregate_counterparty_flows,
    assess_funds_utilization,
    compute_flow_metrics,
)
from app.services.typology_rules import TypologyHit, evaluate_typologies, typology_narrative_block


def _debit_credit(txn: Dict[str, Any]) -> str:
    from app.services.transaction_analytics import _is_inflow, _is_outflow

    if _is_outflow(txn):
        return "Debit (outflow)"
    if _is_inflow(txn):
        return "Credit (inflow)"
    return "Unclassified"


def _serialize_kyc(kyc: Any) -> Dict[str, Any]:
    return {
        "customer_name": kyc.customer_name,
        "account_number": kyc.account_number,
        "account_opened": kyc.account_opened.isoformat(),
        "customer_address": kyc.customer_address,
        "line_of_business": kyc.line_of_business,
        "phone_number": kyc.phone_number,
        "date_of_birth": kyc.date_of_birth.isoformat(),
        "id_number": kyc.id_number,
        "bvn": kyc.id_number,
    }


def _contact_email_for_snapshot(customer_id: str, txn_dict: Dict[str, Any]) -> str:
    """
    On-file email for EDD workflows: prefer transaction metadata, else a stable demo address.
    Replace with the customer's real address before sending live mail.
    """
    md = txn_dict.get("metadata") if isinstance(txn_dict.get("metadata"), dict) else {}
    for key in ("customer_email", "contact_email", "email"):
        raw = md.get(key)
        if isinstance(raw, str) and "@" in raw.strip():
            return raw.strip()
    slug = "".join(c for c in (customer_id or "customer") if c.isalnum() or c in "-_")
    slug = (slug or "customer").lower()
    return f"{slug}@example.com"


def _hits_to_dict(hits: List[TypologyHit]) -> List[Dict[str, str]]:
    return [
        {"rule_id": h.rule_id, "title": h.title, "narrative": h.narrative, "nfiu_reference": h.nfiu_reference}
        for h in hits
    ]


async def build_alert_snapshot(
    *,
    alert: AlertResponse,
    txn: Optional[Dict[str, Any]],
    all_txn_dicts: List[Dict[str, Any]],
    pg: Optional[PostgresClient],
) -> Dict[str, Any]:
    """
    Pre-resolution view: transaction, customer, windows (24h / 12m / lifetime), typologies,
    counterparty flows, sanctions screening, BVN-linked accounts, funds utilisation narrative.
    """
    txn_dict = txn or {
        "id": alert.transaction_id,
        "customer_id": alert.customer_id,
        "amount": 0.0,
        "currency": "NGN",
        "transaction_type": "unknown",
        "narrative": alert.summary,
        "metadata": {},
        "created_at": datetime.utcnow().isoformat(),
    }

    cid = alert.customer_id
    baseline = [t for t in all_txn_dicts if str(t.get("customer_id")) == cid and str(t.get("id")) != str(txn_dict.get("id"))]

    profile_label = ""
    md = txn_dict.get("metadata") or {}
    if isinstance(md, dict):
        profile_label = str(md.get("profile") or md.get("pattern") or "")

    typ_hits = evaluate_typologies(txn_dict, baseline, customer_profile_label=profile_label)

    metrics = compute_flow_metrics(cid, all_txn_dicts)
    inbound, outbound = aggregate_counterparty_flows(cid, all_txn_dicts)

    kyc = await get_or_create_customer_kyc(pg, cid, txn_dict)
    bvn_accounts = await list_bvn_linked_accounts(pg, kyc.id_number, primary_customer_id=cid)

    sanctions = await screen_name_opensanctions(kyc.customer_name)
    san_count = int(sanctions.get("match_count") or 0)

    funds = assess_funds_utilization(txn_dict, [t for t in all_txn_dicts if str(t.get("customer_id")) == cid])

    suspicion = {
        "anomaly_rules": list(alert.rule_ids or []),
        "typologies": _hits_to_dict(typ_hits),
        "summary_lines": [h.narrative for h in typ_hits][:6],
        "nfiu_narrative_addon": typology_narrative_block(typ_hits),
    }

    meta_tx = txn_dict.get("metadata") if isinstance(txn_dict.get("metadata"), dict) else {}
    cp_id = txn_dict.get("counterparty_id") or meta_tx.get("counterparty_id")
    cp_name = txn_dict.get("counterparty_name") or meta_tx.get("counterparty_name")

    customer_profile = _serialize_kyc(kyc)
    customer_profile["email"] = _contact_email_for_snapshot(cid, txn_dict)

    return {
        "alert_id": alert.id,
        "transaction": {
            "id": txn_dict.get("id"),
            "amount": txn_dict.get("amount"),
            "currency": txn_dict.get("currency") or "NGN",
            "transaction_type": txn_dict.get("transaction_type"),
            "debit_credit": _debit_credit(txn_dict),
            "narrative": txn_dict.get("narrative"),
            "created_at": txn_dict.get("created_at"),
            "counterparty_id": cp_id,
            "counterparty_name": cp_name,
            "metadata": txn_dict.get("metadata") or {},
        },
        "customer_profile": customer_profile,
        "bvn_linked_accounts": bvn_accounts,
        "why_suspicious": suspicion,
        "rolling_windows": {
            "real_time_note": "Flags are evaluated at transaction processing time; snapshot uses current store (demo).",
            "last_24_hours": {
                "window_start": metrics.window_24h_start,
                "window_end": metrics.window_24h_end,
                "transaction_count": metrics.txn_count_24h,
                "inflow_total": metrics.inflow_24h,
                "outflow_total": metrics.outflow_24h,
            },
            "twelve_month_ytd": {
                "window_start": metrics.ytd_12m_start,
                "window_end": metrics.ytd_12m_end,
                "inflow_total": metrics.inflow_12m,
                "outflow_total": metrics.outflow_12m,
            },
            "lifetime_for_narrative": {
                "first_seen": metrics.lifetime_start,
                "account_age_days": metrics.account_age_days,
                "total_inflow": metrics.lifetime_inflow,
                "total_outflow": metrics.lifetime_outflow,
                "transaction_count": metrics.lifetime_txn_count,
            },
        },
        "flagged_flows": {
            "top_inbound_sources": [asdict(x) for x in inbound],
            "top_outbound_destinations": [asdict(x) for x in outbound],
        },
        "sanctions_screening": sanctions,
        "adverse_media": adverse_media_placeholder(kyc.customer_name, san_count),
        "funds_utilization": {
            "funds_utilized": funds.funds_utilized,
            "subsequent_outflow_total": funds.subsequent_outflow_total,
            "description": funds.description,
        },
        "severity": alert.severity,
        "status": alert.status,
    }
