from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from app.config import settings
from app.core.logging import get_logger
from app.core.security import get_current_user, require_cco_or_admin
from app.models.alert import (
    AlertResponse,
    CcoActionNotificationRequest,
    CcoOtcApprovalBody,
    CcoRejectBody,
    CcoStrApprovalBody,
    CoNotificationMarkReadBody,
    EddNotificationRequest,
    EscalationRequest,
    InvestigationRequest,
    OtcReportSubmission,
    ResolutionRequest,
    OTC_SUBJECTS_ESAR,
    otc_report_kind_for_subject,
)
from app.services.alert_snapshot import build_alert_snapshot
from app.services.customer_kyc_db import fetch_customer_kyc_any, list_bvn_linked_accounts
from app.api.v1.in_memory_stores import (
    _ALERTS,
    _TXNS,
    co_notifications_for_email,
    mark_co_notifications_read,
    push_co_notification,
)
from app.services.zone_branch import txn_matches_user_scope
from app.services import audit_trail
from app.services.mail_notify import (
    build_cco_action_notification_email,
    build_cco_str_approval_required_email,
    build_co_cco_rejection_email,
    build_edd_request_email,
    send_plain_email,
    send_email_with_attachment,
    _smtp_configured,
)

log = get_logger(component="alerts_api")

_MAX_AUDIT_RATIONALE_CHARS = 16_384


def _audit_rationale(value: Optional[str]) -> Optional[str]:
    """Cap free-text stored in the immutable audit trail (export/SIEM payloads)."""
    if value is None:
        return None
    t = str(value).strip()
    if not t:
        return None
    if len(t) > _MAX_AUDIT_RATIONALE_CHARS:
        return f"{t[:_MAX_AUDIT_RATIONALE_CHARS]}\n[truncated for audit log max length]"
    return t


def _actor_officer_email(user: Dict[str, Any]) -> str:
    return str(user.get("email") or user.get("sub") or "").strip()


def _last_officer_email_from_history(history: List[Dict[str, Any]]) -> Optional[str]:
    """Best-effort compliance officer inbox for CCO rejection notices."""
    for entry in reversed(history or []):
        if not isinstance(entry, dict):
            continue
        em = entry.get("officer_email")
        if em and str(em).strip():
            return str(em).strip()
    return None


async def _enrich_alert_for_api(a: AlertResponse, pg: Any = None) -> AlertResponse:
    """Attach linked transaction hints for list/detail JSON (OTC / ESTR queue tab)."""
    tx = _TXNS.get(a.transaction_id)
    customer_name = (a.customer_name or "").strip() or None
    if not customer_name and tx and isinstance(tx.metadata, dict):
        n0 = str(tx.metadata.get("customer_name") or "").strip()
        customer_name = n0 or None
    if not customer_name:
        try:
            kyc = await fetch_customer_kyc_any(pg, a.customer_id)
            if kyc:
                n1 = str(getattr(kyc, "customer_name", "") or "").strip()
                customer_name = n1 or None
        except Exception:
            pass
    if not tx:
        return a.model_copy(
            update={
                "linked_transaction_type": None,
                "linked_channel": None,
                "walk_in_otc": False,
                "customer_name": customer_name,
            }
        )
    md = tx.metadata if isinstance(tx.metadata, dict) else {}
    channel = str(md.get("channel") or "").strip().lower() or None
    walk = md.get("walk_in") is True or channel == "otc_branch"
    primary_account_number = str(md.get("account_number") or md.get("originator_account") or "").strip() or None
    if not primary_account_number:
        try:
            kyc = await fetch_customer_kyc_any(pg, a.customer_id)
            if kyc:
                primary_account_number = str(getattr(kyc, "account_number", "") or "").strip() or None
        except Exception:
            pass
    return a.model_copy(
        update={
            "linked_transaction_type": tx.transaction_type,
            "linked_channel": channel,
            "walk_in_otc": bool(walk),
            "customer_name": customer_name,
            "primary_account_number": primary_account_number,
        }
    )


def _sort_key_for_alert(a: AlertResponse) -> tuple[float, datetime]:
    return (float(a.severity or 0.0), a.created_at or datetime.min)


async def _bvn_group_key(a: AlertResponse, pg: Any, kyc_cache: Optional[Dict[str, Any]] = None) -> str:
    cid = str(a.customer_id or "").strip()
    kyc = None
    if kyc_cache is not None and cid in kyc_cache:
        kyc = kyc_cache[cid]
    else:
        try:
            kyc = await fetch_customer_kyc_any(pg, cid)
        except Exception:
            kyc = None
        if kyc_cache is not None:
            kyc_cache[cid] = kyc
    try:
        bvn = str(getattr(kyc, "id_number", "") or "").strip()
        if bvn:
            return f"bvn:{bvn.lower()}"
    except Exception:
        pass
    return f"cid:{a.customer_id.lower()}"


def _txn_account_number(tx: Any) -> str:
    if not tx:
        return ""
    md = tx.metadata if isinstance(tx.metadata, dict) else {}
    return (
        str(
            md.get("account_number")
            or md.get("originator_account")
            or md.get("sender_account")
            or md.get("source_account")
            or ""
        ).strip()
    )


async def _attach_linked_context(
    a: AlertResponse,
    pg: Any,
    grouped_alerts: Optional[List[AlertResponse]] = None,
    *,
    include_related_transactions: bool = True,
) -> AlertResponse:
    try:
        kyc = await fetch_customer_kyc_any(pg, a.customer_id)
    except Exception:
        kyc = None
    if not kyc:
        return a
    bvn = str(getattr(kyc, "id_number", "") or "").strip()
    if not bvn:
        return a.model_copy(
            update={
                "linked_accounts_count": 1 if a.primary_account_number else 0,
                "linked_accounts": [
                    {
                        "customer_id": a.customer_id,
                        "customer_name": a.customer_name,
                        "account_number": a.primary_account_number,
                    }
                ]
                if a.primary_account_number
                else [],
            }
        )
    linked = await list_bvn_linked_accounts(pg, bvn, primary_customer_id=a.customer_id)
    linked_cids = {str(r.get("customer_id") or "").strip() for r in linked if isinstance(r, dict)}
    linked_cids.discard("")
    linked_accounts = [
        {
            "customer_id": str(r.get("customer_id") or "").strip(),
            "customer_name": str(r.get("customer_name") or "").strip() or None,
            "account_number": str(r.get("account_number") or "").strip() or None,
            "bvn": str(r.get("bvn") or bvn),
        }
        for r in linked
        if isinstance(r, dict)
    ]
    account_set = {str(x.get("account_number") or "").strip() for x in linked_accounts}
    account_set.discard("")
    seeded_tx_ids = {x.transaction_id for x in (grouped_alerts or [a])}
    related_rows: List[Dict[str, Any]] = []
    if include_related_transactions:
        for tx in _TXNS.values():
            tx_cid = str(getattr(tx, "customer_id", "") or "").strip()
            if tx_cid not in linked_cids:
                continue
            md = tx.metadata if isinstance(tx.metadata, dict) else {}
            from_acct = _txn_account_number(tx)
            to_acct = str(
                md.get("beneficiary_account")
                or md.get("receiver_account")
                or md.get("destination_account")
                or md.get("counterparty_account")
                or ""
            ).strip()
            include = tx.id in seeded_tx_ids
            if not include and account_set:
                include = (from_acct in account_set) or (to_acct in account_set)
            if not include:
                continue
            related_rows.append(
                {
                    "transaction_id": tx.id,
                    "customer_id": tx_cid,
                    "transaction_type": tx.transaction_type,
                    "amount": float(tx.amount or 0.0),
                    "currency": tx.currency or "NGN",
                    "from_account": from_acct or None,
                    "to_account": to_acct or None,
                    "narrative": tx.narrative,
                    "channel": str(md.get("channel") or "").strip() or None,
                    "created_at": tx.created_at.isoformat() if getattr(tx, "created_at", None) else None,
                    "seeded_by_alert": tx.id in seeded_tx_ids,
                }
            )
        related_rows.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return a.model_copy(
        update={
            "linked_accounts_count": len(linked_accounts),
            "linked_accounts": linked_accounts,
            "related_transactions": related_rows[:40],
        }
    )


async def _collapse_alerts_for_table(items: List[AlertResponse], pg: Any) -> List[AlertResponse]:
    grouped: Dict[str, List[AlertResponse]] = {}
    kyc_cache: Dict[str, Any] = {}
    for a in items:
        key = await _bvn_group_key(a, pg, kyc_cache)
        grouped.setdefault(key, []).append(a)
    out: List[AlertResponse] = []
    for group in grouped.values():
        group.sort(key=_sort_key_for_alert, reverse=True)
        top = await _enrich_alert_for_api(group[0], pg)
        top = await _attach_linked_context(top, pg, grouped_alerts=group, include_related_transactions=False)
        out.append(top)
    out.sort(key=_sort_key_for_alert, reverse=True)
    return out


def _alert_matches_otc_estr_queue(a: AlertResponse) -> bool:
    """
    OTC ESTR queue:
    - explicitly marked otc_estr path, OR
    - walk-in OTC cash activity (branch/walk-in channel).
    Excludes ATM/POS/transfer-led alerts, which stay on the core STR alert tab.
    """
    tx = _TXNS.get(a.transaction_id)
    kind = str(getattr(a, "otc_report_kind", "") or "").strip().lower()
    subject = str(getattr(a, "otc_subject", "") or "").strip()
    if kind == "otc_esar" or subject in OTC_SUBJECTS_ESAR:
        return False
    if kind == "otc_estr":
        return True
    if tx:
        tt = (tx.transaction_type or "").lower()
        md = tx.metadata if isinstance(tx.metadata, dict) else {}
        ch = str(md.get("channel") or "").strip().lower()
        walk = md.get("walk_in") is True or ch == "otc_branch"
        if walk and tt in ("cash_deposit", "cash_withdrawal"):
            return True
    return False


def _alert_matches_otc_esar_queue(a: AlertResponse) -> bool:
    """
    OTC ESAR queue:
    - identity/profile OTC matters (partial/full name, BVN/NIN, DOB updates)
    - walk-in OTC records explicitly set to otc_esar path
    """
    kind = str(getattr(a, "otc_report_kind", "") or "").strip().lower()
    subject = str(getattr(a, "otc_subject", "") or "").strip()
    if kind == "otc_esar" or subject in OTC_SUBJECTS_ESAR:
        return True
    return False


def _alert_matches_core_alert_tab(a: AlertResponse) -> bool:
    """Main Alerts tab: non-OTC or transaction-led alerts (e.g., transfer in/out)."""
    return not _alert_matches_otc_estr_queue(a) and not _alert_matches_otc_esar_queue(a)


def _alert_visible_to_user(user: Dict[str, Any], a: AlertResponse) -> bool:
    t = _TXNS.get(a.transaction_id)
    if t:
        return txn_matches_user_scope(user, t.metadata, t.customer_id)
    return txn_matches_user_scope(user, None, a.customer_id)

router = APIRouter(prefix="/alerts")

_SEVERITY_BUCKETS = ("low", "medium", "high", "critical")


def _alert_in_severity_bucket(sev: float, bucket: str) -> bool:
    b = (bucket or "").strip().lower()
    if b not in _SEVERITY_BUCKETS:
        return True
    s = float(sev or 0.0)
    if b == "low":
        return s < 0.5
    if b == "medium":
        return 0.5 <= s < 0.75
    if b == "high":
        return 0.75 <= s < 0.9
    return s >= 0.9


def _seed_if_empty() -> None:
    """Disabled: demo data comes from /demo/seed or /demo/simulate-temporal only."""
    return


def _alert_not_soft_deleted(a: AlertResponse) -> bool:
    return getattr(a, "deleted_at", None) is None


@router.get("/", response_model=Dict[str, Any])
async def list_alerts(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    severity: Optional[str] = Query(
        None,
        description="Filter: low | medium | high | critical (same bands as dashboard)",
    ),
    status: Optional[str] = None,
    sort: str = Query("risk", pattern="^(risk|newest)$"),
    queue: Optional[str] = Query(
        None,
        description="Optional filter: core | otc_estr | otc_esar",
    ),
    user: Dict[str, Any] = Depends(get_current_user),
):
    _seed_if_empty()

    items = [
        a
        for a in _ALERTS.values()
        if _alert_visible_to_user(user, a) and _alert_not_soft_deleted(a)
    ]
    qk = (queue or "").strip().lower()
    if qk == "otc_estr":
        items = [a for a in items if _alert_matches_otc_estr_queue(a)]
    elif qk == "otc_esar":
        items = [a for a in items if _alert_matches_otc_esar_queue(a)]
    elif qk == "core":
        items = [a for a in items if _alert_matches_core_alert_tab(a)]
    if status:
        st = status.strip().lower()
        items = [a for a in items if (a.status or "").lower() == st]
    if severity and severity.strip().lower() in _SEVERITY_BUCKETS:
        items = [a for a in items if _alert_in_severity_bucket(a.severity or 0.0, severity)]
    if sort == "newest":
        items.sort(key=lambda a: a.created_at or datetime.min, reverse=True)
    else:
        items.sort(key=lambda a: (a.severity or 0.0), reverse=True)
    pg = getattr(request.app.state, "pg", None)
    collapsed = await _collapse_alerts_for_table(items, pg)
    total = len(collapsed)
    out = collapsed[skip : skip + limit]
    return {"items": out, "total": total, "skip": skip, "limit": limit}


@router.get("/search", response_model=Dict[str, Any])
async def search_alerts(
    request: Request,
    q: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sort: str = Query("risk", pattern="^(risk|newest)$"),
    queue: Optional[str] = Query(
        None,
        description="Optional filter: core | otc_estr | otc_esar",
    ),
    user: Dict[str, Any] = Depends(get_current_user),
):
    _seed_if_empty()
    ql = q.strip().lower()
    items = [
        a
        for a in _ALERTS.values()
        if _alert_visible_to_user(user, a)
        and _alert_not_soft_deleted(a)
        and (
            (a.summary or "").lower().find(ql) >= 0
            or a.customer_id.lower().find(ql) >= 0
            or (str(getattr(a, "customer_name", "") or "").lower().find(ql) >= 0)
            or a.transaction_id.lower().find(ql) >= 0
            or a.id.lower().find(ql) >= 0
        )
    ]
    qk = (queue or "").strip().lower()
    if qk == "otc_estr":
        items = [a for a in items if _alert_matches_otc_estr_queue(a)]
    elif qk == "otc_esar":
        items = [a for a in items if _alert_matches_otc_esar_queue(a)]
    elif qk == "core":
        items = [a for a in items if _alert_matches_core_alert_tab(a)]
    if status:
        st = status.strip().lower()
        items = [a for a in items if (a.status or "").lower() == st]
    if severity and severity.strip().lower() in _SEVERITY_BUCKETS:
        items = [a for a in items if _alert_in_severity_bucket(a.severity or 0.0, severity)]
    if sort == "newest":
        items.sort(key=lambda a: a.created_at or datetime.min, reverse=True)
    else:
        items.sort(key=lambda a: (a.severity or 0.0), reverse=True)
    pg = getattr(request.app.state, "pg", None)
    collapsed = await _collapse_alerts_for_table(items, pg)
    total = len(collapsed)
    out = collapsed[skip : skip + limit]
    return {"items": out, "total": total, "skip": skip, "limit": limit}


def _severity_trend_bucket(severity: float) -> str:
    if severity >= 0.9:
        return "critical"
    if severity >= 0.75:
        return "high"
    if severity >= 0.5:
        return "medium"
    return "low"


def _alerts_dashboard_payload(user: Dict[str, Any]) -> Dict[str, Any]:
    """MI-style aggregates for dashboard UI and CSV export (scoped to user visibility)."""
    now = datetime.utcnow()
    today = now.date()
    visible = [
        a for a in _ALERTS.values() if _alert_visible_to_user(user, a) and _alert_not_soft_deleted(a)
    ]

    counts_by_severity = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    counts_by_status: Dict[str, int] = {}
    for a in visible:
        if a.severity >= 0.9:
            counts_by_severity["critical"] += 1
        elif a.severity >= 0.75:
            counts_by_severity["high"] += 1
        elif a.severity >= 0.5:
            counts_by_severity["medium"] += 1
        else:
            counts_by_severity["low"] += 1
        st = a.status or "unknown"
        counts_by_status[st] = counts_by_status.get(st, 0) + 1

    trend_keys = [(today - timedelta(days=d)).isoformat() for d in range(29, -1, -1)]
    trend_map: Dict[str, Dict[str, int]] = {
        k: {"critical": 0, "high": 0, "medium": 0, "low": 0} for k in trend_keys
    }
    for a in visible:
        ca = a.created_at
        if not isinstance(ca, datetime):
            continue
        dk = ca.date().isoformat()
        if dk not in trend_map:
            continue
        b = _severity_trend_bucket(float(a.severity or 0.0))
        trend_map[dk][b] += 1
    trend_over_time = [{"date": k, **trend_map[k]} for k in trend_keys]

    resolution_hours: List[float] = []
    for a in visible:
        if (a.status or "").lower() != "closed":
            continue
        start = a.created_at
        end = a.updated_at or a.created_at
        if isinstance(start, datetime) and isinstance(end, datetime) and end >= start:
            resolution_hours.append((end - start).total_seconds() / 3600.0)
    average_resolution_time_hours: Optional[float] = None
    if resolution_hours:
        average_resolution_time_hours = round(sum(resolution_hours) / len(resolution_hours), 2)

    open_case_ageing = {"lt_24h": 0, "d1_3": 0, "d3_7": 0, "gt_7d": 0}
    for a in visible:
        if (a.status or "").lower() in ("closed", "rejected"):
            continue
        start = a.created_at
        if not isinstance(start, datetime):
            continue
        age_h = max(0.0, (now - start).total_seconds() / 3600.0)
        if age_h < 24:
            open_case_ageing["lt_24h"] += 1
        elif age_h < 72:
            open_case_ageing["d1_3"] += 1
        elif age_h < 168:
            open_case_ageing["d3_7"] += 1
        else:
            open_case_ageing["gt_7d"] += 1

    outcome_summary = {
        "closed_false_positive": 0,
        "closed_other": 0,
        "escalated": 0,
        "investigating": 0,
        "open": 0,
        "rejected": 0,
    }
    otc_outcome_counts = {"true_positive": 0, "false_positive": 0, "not_filed": 0}
    for a in visible:
        st = (a.status or "").lower()
        if st == "closed":
            if (a.last_resolution or "").strip() == "false_positive":
                outcome_summary["closed_false_positive"] += 1
            else:
                outcome_summary["closed_other"] += 1
        elif st == "rejected":
            outcome_summary["rejected"] += 1
        elif st == "escalated":
            outcome_summary["escalated"] += 1
        elif st == "investigating":
            outcome_summary["investigating"] += 1
        else:
            outcome_summary["open"] += 1
        oo = a.otc_outcome
        if oo == "true_positive":
            otc_outcome_counts["true_positive"] += 1
        elif oo == "false_positive":
            otc_outcome_counts["false_positive"] += 1
        else:
            otc_outcome_counts["not_filed"] += 1

    pending_cco_str = sum(
        1
        for a in visible
        if (a.status or "").lower() == "escalated"
        and not a.cco_str_approved
        and getattr(a, "otc_report_kind", None) not in ("otc_estr", "otc_esar")
    )
    pending_cco_otc = sum(
        1
        for a in visible
        if (a.otc_outcome or "") == "true_positive"
        and bool(getattr(a, "otc_report_kind", None))
        and not bool(getattr(a, "cco_otc_approved", False))
        and (a.status or "").lower() == "escalated"
    )
    pending_cco_estr_word = 0

    role_l = (user.get("role") or "").strip().lower()
    email_u = (user.get("email") or "").strip().lower()
    co_notifications: List[Dict[str, Any]] = []
    if email_u and role_l in ("compliance_officer", "admin", "chief_compliance_officer"):
        co_notifications = co_notifications_for_email(email_u, unread_only=True)[:50]

    return {
        "counts_by_severity": counts_by_severity,
        "counts_by_status": counts_by_status,
        "trend_over_time": trend_over_time,
        "average_resolution_time_hours": average_resolution_time_hours,
        "open_case_ageing": open_case_ageing,
        "outcome_summary": outcome_summary,
        "otc_outcome_counts": otc_outcome_counts,
        "closed_cases_in_avg_sample": len(resolution_hours),
        "pending_cco_str_approvals": pending_cco_str,
        "pending_cco_otc_approvals": pending_cco_otc,
        "pending_cco_estr_word_approvals": pending_cco_estr_word,
        "co_notifications_unread": co_notifications,
    }


@router.get("/dashboard")
async def dashboard(user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    return _alerts_dashboard_payload(user)


@router.get("/dashboard/mi-export")
async def dashboard_mi_export(user: Dict[str, Any] = Depends(get_current_user)):
    """CSV snapshot of alert MI (management information) for the signed-in user's scope."""
    _seed_if_empty()
    d = _alerts_dashboard_payload(user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "metric", "value"])
    w.writerow(["summary", "average_resolution_time_hours", d.get("average_resolution_time_hours") or ""])
    w.writerow(["summary", "closed_cases_in_avg_sample", d.get("closed_cases_in_avg_sample", 0)])
    w.writerow(["summary", "pending_cco_str_approvals", d.get("pending_cco_str_approvals", 0)])
    w.writerow(["summary", "pending_cco_otc_approvals", d.get("pending_cco_otc_approvals", 0)])
    w.writerow(["summary", "pending_cco_estr_word_approvals", d.get("pending_cco_estr_word_approvals", 0)])
    for k, v in (d.get("counts_by_severity") or {}).items():
        w.writerow(["severity", k, v])
    for k, v in (d.get("counts_by_status") or {}).items():
        w.writerow(["status", k, v])
    for k, v in (d.get("open_case_ageing") or {}).items():
        w.writerow(["open_case_ageing_hours", k, v])
    for k, v in (d.get("outcome_summary") or {}).items():
        w.writerow(["outcome_summary", k, v])
    for k, v in (d.get("otc_outcome_counts") or {}).items():
        w.writerow(["otc_outcome", k, v])
    for row in d.get("trend_over_time") or []:
        w.writerow(
            [
                "trend_by_severity",
                str(row.get("date") or ""),
                json.dumps(
                    {
                        "critical": int(row.get("critical") or 0),
                        "high": int(row.get("high") or 0),
                        "medium": int(row.get("medium") or 0),
                        "low": int(row.get("low") or 0),
                    }
                ),
            ]
        )
    body = buf.getvalue()
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="alert_mi_summary.csv"'},
    )


@router.post("/co-notifications/mark-read")
async def co_notifications_mark_read(
    body: CoNotificationMarkReadBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Mark CCO→CO rejection (and other) in-app notifications as read for the signed-in user's email."""
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="User profile has no email; cannot match notifications.")
    n = mark_co_notifications_read(email, body.notification_ids)
    return {"marked_read": n, "email": email}


@router.get("/cco/pending-str-approvals", response_model=Dict[str, Any])
async def list_pending_cco_str_approvals(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Escalated alerts awaiting Chief Compliance Officer approval before STR generation."""
    require_cco_or_admin(user)
    _seed_if_empty()
    pg = getattr(request.app.state, "pg", None)
    base_items = [
        a
        for a in _ALERTS.values()
        if (a.status or "").lower() == "escalated"
        and not a.cco_str_approved
        and getattr(a, "otc_report_kind", None) not in ("otc_estr", "otc_esar")
    ]
    items = await _collapse_alerts_for_table(base_items, pg)
    total = len(items)
    return {"items": items[skip : skip + limit], "total": total, "skip": skip, "limit": limit}


def _can_view_pending_otc_queue(user: Dict[str, Any]) -> bool:
    role = (user.get("role") or "").strip().lower()
    return role in ("admin", "chief_compliance_officer", "compliance_officer")


@router.get("/cco/pending-otc-approvals", response_model=Dict[str, Any])
async def list_pending_cco_otc_approvals(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """
    True-positive OTC filings awaiting CCO approval for regulatory reporting (ESTR / ESAR paths).
    Only alerts already **escalated** by a compliance officer appear here.
    """
    if not _can_view_pending_otc_queue(user):
        raise HTTPException(
            status_code=403,
            detail="Chief Compliance Officer, Administrator, or Compliance Officer role required to view this queue.",
        )
    _seed_if_empty()
    pg = getattr(request.app.state, "pg", None)
    base_items = [
        a
        for a in _ALERTS.values()
        if (a.otc_outcome or "") == "true_positive"
        and bool(getattr(a, "otc_report_kind", None))
        and not bool(getattr(a, "cco_otc_approved", False))
        and (a.status or "").lower() == "escalated"
        and _alert_visible_to_user(user, a)
    ]
    items = await _collapse_alerts_for_table(base_items, pg)
    total = len(items)
    return {"items": items[skip : skip + limit], "total": total, "skip": skip, "limit": limit}


@router.post("/{alert_id}/otc-report", response_model=Dict[str, Any])
async def submit_otc_report(
    alert_id: str,
    body: OtcReportSubmission,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Compliance officer: file OTC assessment (false positive ends path; true positive unlocks regulatory flags — see OTC ESTR vs ESAR flows)."""
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _alert_visible_to_user(user, a):
        raise HTTPException(status_code=403, detail="Alert outside your zone/branch scope.")
    if a.cco_otc_approved:
        raise HTTPException(
            status_code=400,
            detail="OTC filing is already on file. For OTC ESTR (cash), draft the extended return on Regulatory Reports when eligible.",
        )

    now = datetime.utcnow()
    detail_trim = (body.filing_reason_detail or "").strip() or None
    rationale_trim = (body.officer_rationale or "").strip() or None

    hist_base: Dict[str, Any] = {
        "action": "otc_report",
        "filing_reason": body.filing_reason,
        "filing_reason_detail": detail_trim,
        "outcome": body.outcome,
        "subject": body.subject,
        "at": now.isoformat() + "Z",
    }
    oe_otc = _actor_officer_email(user)
    if oe_otc:
        hist_base["officer_email"] = oe_otc

    if body.outcome == "false_positive":
        a.otc_filing_reason = body.filing_reason
        a.otc_filing_reason_detail = detail_trim if body.filing_reason == "other" else None
        a.otc_outcome = "false_positive"
        a.otc_subject = body.subject
        a.otc_officer_rationale = None
        a.otc_report_kind = None
        a.cco_otc_approved = False
        a.cco_estr_word_approved = False
        a.otc_submitted_at = now
        hist_base["otc_report_kind"] = None
        hist_base["officer_rationale"] = None
    else:
        kind = otc_report_kind_for_subject(body.subject)
        a.otc_filing_reason = body.filing_reason
        a.otc_filing_reason_detail = detail_trim if body.filing_reason == "other" else None
        a.otc_outcome = "true_positive"
        a.otc_subject = body.subject
        a.otc_officer_rationale = rationale_trim
        a.otc_report_kind = kind
        auto_otc = bool(getattr(settings, "cco_auto_approve_otc_reporting", False))
        a.cco_otc_approved = auto_otc
        a.cco_estr_word_approved = False
        a.otc_submitted_at = now
        hist_base["otc_report_kind"] = kind
        hist_base["officer_rationale"] = rationale_trim
        if auto_otc:
            hist_base["cco_otc_auto_approved_via_admin_setting"] = True

    a.updated_at = now
    a.investigation_history.append(hist_base)
    _ALERTS[alert_id] = a

    aud: Dict[str, Any] = {
        "outcome": body.outcome,
        "subject": body.subject,
        "filing_reason": body.filing_reason,
        "customer_id": a.customer_id,
        "transaction_id": a.transaction_id,
    }
    if body.outcome == "true_positive":
        aud["otc_report_kind"] = a.otc_report_kind
        if rationale_trim:
            n = _audit_rationale(rationale_trim)
            if n:
                aud["officer_rationale"] = n
    audit_trail.record_event_from_user(
        user,
        action="alert.otc_report",
        resource_type="alert",
        resource_id=alert_id,
        details=aud,
    )

    return {
        "alert_id": alert_id,
        "otc_outcome": a.otc_outcome,
        "otc_report_kind": a.otc_report_kind,
        "cco_otc_approved": a.cco_otc_approved,
        "action_key": str(uuid4()),
    }


@router.post("/{alert_id}/cco-approve-otc", response_model=Dict[str, Any])
async def cco_approve_otc_filing(
    request: Request,
    alert_id: str,
    body: CcoOtcApprovalBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_cco_or_admin(user)
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if (a.status or "").lower() != "escalated":
        raise HTTPException(
            status_code=400,
            detail="The compliance officer must escalate this alert before you can approve OTC reporting.",
        )
    if (a.otc_outcome or "") != "true_positive":
        raise HTTPException(status_code=400, detail="Only true-positive OTC filings can be CCO-approved for reporting.")
    if not a.otc_report_kind:
        raise HTTPException(status_code=400, detail="OTC report type is not set on this alert.")
    if a.cco_otc_approved:
        raise HTTPException(status_code=400, detail="This OTC filing is already approved.")
    a.cco_otc_approved = True
    a.updated_at = datetime.utcnow()
    approver = str(user.get("display_name") or user.get("email") or user.get("sub") or "CCO")
    a.investigation_history.append(
        {
            "action": "cco_approve_otc",
            "notes": (body.notes or "").strip() or None,
            "approved_by": approver,
            "otc_report_kind": a.otc_report_kind,
            "at": a.updated_at.isoformat() + "Z",
        }
    )
    _ALERTS[alert_id] = a
    cco_details: Dict[str, Any] = {
        "approved_by": approver,
        "customer_id": a.customer_id,
        "transaction_id": a.transaction_id,
        "otc_report_kind": a.otc_report_kind,
    }
    cco_notes = _audit_rationale(body.notes)
    if cco_notes:
        cco_details["notes"] = cco_notes
    audit_trail.record_event_from_user(
        user,
        action="alert.cco_approve_otc",
        resource_type="alert",
        resource_id=alert_id,
        details=cco_details,
    )
    estr_draft_report_id: Optional[str] = None
    if a.otc_report_kind in ("otc_estr", "otc_esar"):
        try:
            import app.api.v1.reports as reports_v1

            draft = await reports_v1._create_estr_draft(
                request,
                user,
                base_alert=alert_id,
                user_notes=(body.notes or "").strip(),
            )
            estr_draft_report_id = str(draft.get("report_id") or "") or None
        except Exception as exc:
            log.warning("cco_otc_approval_estr_draft_failed alert_id=%s err=%s", alert_id, exc)
    return {
        "alert_id": alert_id,
        "cco_otc_approved": True,
        "otc_report_kind": a.otc_report_kind,
        "cco_estr_word_approved": a.cco_estr_word_approved,
        "estr_draft_report_id": estr_draft_report_id,
        "otc_draft_report_id": estr_draft_report_id,
        "action_key": str(uuid4()),
    }


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: str, request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _alert_not_soft_deleted(a):
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _alert_visible_to_user(user, a):
        raise HTTPException(status_code=403, detail="Alert outside your zone/branch scope.")
    pg = getattr(request.app.state, "pg", None)
    enriched = await _enrich_alert_for_api(a, pg)
    return await _attach_linked_context(enriched, pg)


@router.post("/{alert_id}/reset-workflow", response_model=Dict[str, Any])
async def reset_alert_workflow(alert_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """
    Demo / QA: return the alert to **open** and clear STR and escalation flags.
    Preserves customer/transaction links, summary, severity, rule_ids, and OTC filing fields (e.g. true-positive assessment).
    """
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _alert_visible_to_user(user, a):
        raise HTTPException(status_code=403, detail="Alert outside your zone/branch scope.")
    now = datetime.utcnow()
    prev_status = a.status
    a.status = "open"
    a.escalated_to_cco = False
    a.cco_str_approved = False
    a.cco_str_rejected = False
    a.cco_str_rejection_reason = None
    a.cco_otc_approved = False
    a.cco_estr_word_approved = False
    a.escalation_classification = None
    a.escalation_reason_notes = None
    a.last_resolution = None
    a.updated_at = now
    a.investigation_history.append(
        {
            "action": "workflow_reset",
            "previous_status": prev_status,
            "at": now.isoformat() + "Z",
            "by": str(user.get("email") or user.get("sub") or "user"),
        }
    )
    _ALERTS[alert_id] = a
    audit_trail.record_event_from_user(
        user,
        action="alert.workflow_reset",
        resource_type="alert",
        resource_id=alert_id,
        details={"previous_status": prev_status, "customer_id": a.customer_id},
    )
    return {"alert_id": alert_id, "status": a.status, "action_key": str(uuid4())}


@router.get("/{alert_id}/snapshot")
async def get_alert_snapshot(
    alert_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Pre-resolution view: transaction, customer, BVN-linked accounts, 24h/12m/lifetime metrics,
    typologies, counterparty flows, sanctions screening, funds utilisation narrative.
    """
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _alert_visible_to_user(user, a):
        raise HTTPException(status_code=403, detail="Alert outside your zone/branch scope.")

    txn = _TXNS.get(a.transaction_id)
    txn_dict = txn.model_dump() if txn else None
    all_tx = [t.model_dump() for t in _TXNS.values()]
    pg = getattr(request.app.state, "pg", None)
    return await build_alert_snapshot(alert=a, txn=txn_dict, all_txn_dicts=all_tx, pg=pg)


@router.post("/{alert_id}/notify/edd")
async def notify_edd(
    alert_id: str,
    body: EddNotificationRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _smtp_configured():
        raise HTTPException(
            status_code=503,
            detail="SMTP not configured. Set SMTP_HOST, SMTP_FROM_EMAIL, and related variables.",
        )
    txn = _TXNS.get(a.transaction_id)
    cname = body.customer_name or a.customer_id
    analyst = str(user.get("display_name") or user.get("email") or user.get("sub") or "Compliance")
    subj, text = build_edd_request_email(
        customer_name=cname,
        customer_email=body.customer_email,
        alert_id=a.id,
        transaction_id=a.transaction_id,
        summary=a.summary or "",
        requested_by=analyst,
        compliance_action=body.compliance_action,
        investigator_id=body.investigator_id,
        investigation_notes=body.investigation_notes,
        resolution=body.resolution,
        resolution_notes=body.resolution_notes,
        escalate_reason=body.escalate_reason,
        escalated_to=body.escalated_to,
        additional_note=body.additional_note,
    )
    await send_plain_email([body.customer_email], subj, text)
    out: Dict[str, Any] = {"status": "sent", "to": body.customer_email, "type": "edd"}
    if body.compliance_action:
        out["compliance_action"] = body.compliance_action
    return out


@router.post("/{alert_id}/notify/cco")
async def notify_cco(
    alert_id: str,
    body: CcoActionNotificationRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _smtp_configured():
        raise HTTPException(
            status_code=503,
            detail="SMTP not configured. Set SMTP_HOST, SMTP_FROM_EMAIL, and related variables.",
        )
    cco = (settings.cco_email or "").strip()
    if not cco:
        raise HTTPException(status_code=503, detail="CCO_EMAIL is not set.")
    analyst = str(user.get("display_name") or user.get("email") or user.get("sub") or "Compliance")
    subj, text = build_cco_action_notification_email(
        cco_name_or_role="Chief Compliance Officer",
        alert_id=a.id,
        customer_id=a.customer_id,
        transaction_id=a.transaction_id,
        summary=a.summary or "",
        analyst=analyst,
        action=body.action,
        investigator_id=body.investigator_id,
        investigation_notes=body.investigation_notes,
        resolution=body.resolution,
        resolution_notes=body.resolution_notes,
        escalate_reason=body.escalate_reason,
        escalated_to=body.escalated_to,
        additional_note=body.additional_note,
    )
    to_addrs = [cco]
    for extra in body.extra_recipients or []:
        e = str(extra).strip().lower()
        if e and e not in {x.strip().lower() for x in to_addrs}:
            to_addrs.append(str(extra))
    await send_plain_email(to_addrs, subj, text)
    return {"status": "sent", "to": ", ".join(to_addrs), "type": "cco", "action": body.action}


@router.post("/{alert_id}/investigate")
async def investigate(alert_id: str, body: InvestigationRequest, user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    a.status = "investigating"
    a.updated_at = datetime.utcnow()
    oe = _actor_officer_email(user)
    inv_entry: Dict[str, Any] = {
        "action": "investigate",
        "investigator_id": body.investigator_id,
        "notes": body.notes,
        "at": a.updated_at.isoformat(),
    }
    if oe:
        inv_entry["officer_email"] = oe
    a.investigation_history.append(inv_entry)
    _ALERTS[alert_id] = a
    inv_details: Dict[str, Any] = {
        "investigator_id": body.investigator_id,
        "customer_id": a.customer_id,
        "transaction_id": a.transaction_id,
    }
    notes = _audit_rationale(body.notes)
    if notes:
        inv_details["notes"] = notes
    audit_trail.record_event_from_user(
        user,
        action="alert.investigate",
        resource_type="alert",
        resource_id=alert_id,
        details=inv_details,
    )
    return {"alert_id": alert_id, "status": a.status, "investigator_id": body.investigator_id, "action_key": str(uuid4())}


@router.post("/{alert_id}/resolve")
async def resolve(alert_id: str, body: ResolutionRequest, user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    a.status = "closed"
    a.last_resolution = body.resolution
    a.escalated_to_cco = False
    a.cco_str_approved = False
    a.cco_str_rejected = False
    a.cco_str_rejection_reason = None
    a.escalation_classification = None
    a.escalation_reason_notes = None
    a.updated_at = datetime.utcnow()
    oe = _actor_officer_email(user)
    res_entry: Dict[str, Any] = {
        "action": "resolve",
        "resolution": body.resolution,
        "notes": body.notes,
        "action_taken": body.action_taken,
        "at": a.updated_at.isoformat(),
    }
    if oe:
        res_entry["officer_email"] = oe
    a.investigation_history.append(res_entry)
    _ALERTS[alert_id] = a
    res_details: Dict[str, Any] = {
        "resolution": body.resolution,
        "customer_id": a.customer_id,
        "transaction_id": a.transaction_id,
    }
    rn = _audit_rationale(body.notes)
    if rn:
        res_details["notes"] = rn
    at = _audit_rationale(body.action_taken)
    if at:
        res_details["action_taken"] = at
    audit_trail.record_event_from_user(
        user,
        action="alert.resolve",
        resource_type="alert",
        resource_id=alert_id,
        details=res_details,
    )
    return {"alert_id": alert_id, "resolution": body.resolution, "status": a.status, "action_key": str(uuid4())}


@router.post("/{alert_id}/escalate")
async def escalate(alert_id: str, body: EscalationRequest, user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    to = body.escalated_to.strip()
    reason_display = body.reason.strip() or (
        "Confirmed suspicious activity — true positive escalation."
        if body.escalation_type == "true_positive"
        else body.reason.strip()
    )
    esc_notes = body.reason.strip()
    if not esc_notes and body.escalation_type == "true_positive":
        esc_notes = "Confirmed suspicious activity — true positive escalation."
    a.status = "escalated"
    a.escalated_to_cco = True
    a.cco_str_approved = False
    a.escalation_classification = body.escalation_type
    a.escalation_reason_notes = esc_notes or None
    a.updated_at = datetime.utcnow()
    rk_esc = getattr(a, "otc_report_kind", None)
    if getattr(settings, "cco_auto_approve_str_on_escalation", False) and body.escalation_type == "true_positive":
        if rk_esc not in ("otc_estr", "otc_esar"):
            a.cco_str_approved = True
    if getattr(settings, "cco_auto_approve_otc_reporting", False) and (a.otc_outcome or "") == "true_positive":
        a.cco_otc_approved = True
    esc_entry: Dict[str, Any] = {
        "action": "escalate",
        "escalation_type": body.escalation_type,
        "reason": reason_display,
        "escalated_to": to,
        "at": a.updated_at.isoformat(),
    }
    oe_esc = _actor_officer_email(user)
    if oe_esc:
        esc_entry["officer_email"] = oe_esc
    a.investigation_history.append(esc_entry)
    _ALERTS[alert_id] = a

    cco = (settings.cco_email or "").strip()
    cco_email_notified = False
    cco_notification_detail = ""
    if _smtp_configured() and cco:
        try:
            analyst = str(user.get("display_name") or user.get("email") or user.get("sub") or "Compliance")
            subj, text = build_cco_str_approval_required_email(
                cco_name_or_role="Chief Compliance Officer",
                alert_id=a.id,
                customer_id=a.customer_id,
                transaction_id=a.transaction_id,
                summary=a.summary or "",
                analyst=analyst,
                escalation_type=body.escalation_type,
                reason=reason_display,
                escalated_to=to,
            )
            await send_plain_email([cco], subj, text)
            cco_email_notified = True
            cco_notification_detail = f"Email notification sent to CCO at {cco}."
        except Exception as exc:
            log.warning("cco_escalation_email_failed alert_id=%s err=%s", alert_id, exc)
            cco_notification_detail = (
                f"Escalation recorded, but the CCO email could not be sent ({exc}). Check SMTP configuration and logs."
            )
    elif not cco:
        log.info("cco_email_not_set skip_auto_notify alert_id=%s", alert_id)
        cco_notification_detail = (
            "Escalation recorded. No email was sent: CCO_EMAIL is not set. "
            "Set CCO_EMAIL and SMTP settings so the Chief Compliance Officer receives email, or they can use the CCO review queue in the app."
        )
    else:
        cco_notification_detail = (
            "Escalation recorded. No email was sent: SMTP is not configured (e.g. SMTP_HOST, SMTP_FROM_EMAIL). "
            "The Chief Compliance Officer can still open CCO review in the app for pending approvals."
        )

    esc_details: Dict[str, Any] = {
        "escalation_type": body.escalation_type,
        "escalated_to": to,
        "customer_id": a.customer_id,
        "transaction_id": a.transaction_id,
    }
    rsn = _audit_rationale(reason_display)
    if rsn:
        esc_details["reason"] = rsn
    audit_trail.record_event_from_user(
        user,
        action="alert.escalate",
        resource_type="alert",
        resource_id=alert_id,
        details=esc_details,
    )
    return {
        "alert_id": alert_id,
        "status": a.status,
        "escalated_to": to,
        "escalation_type": body.escalation_type,
        "cco_str_approved": a.cco_str_approved,
        "cco_otc_approved": a.cco_otc_approved,
        "cco_email_notified": cco_email_notified,
        "cco_notification_detail": cco_notification_detail,
        "action_key": str(uuid4()),
    }


@router.post("/{alert_id}/cco-approve-str")
async def cco_approve_str_filing(
    request: Request,
    alert_id: str,
    body: CcoStrApprovalBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Record CCO approval so the alert becomes eligible for STR generation."""
    require_cco_or_admin(user)
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if (a.status or "").lower() != "escalated":
        raise HTTPException(status_code=400, detail="Only escalated alerts can be approved for STR.")
    if getattr(a, "otc_report_kind", None) == "otc_estr":
        raise HTTPException(
            status_code=400,
            detail="OTC ESTR (cash) alerts are not approved for STR. Use Approve ESTR (Word) on the OTC ESTR queue instead.",
        )
    if a.cco_str_approved:
        raise HTTPException(status_code=400, detail="This alert is already approved for STR.")
    a.cco_str_approved = True
    a.updated_at = datetime.utcnow()
    approver = str(user.get("display_name") or user.get("email") or user.get("sub") or "CCO")
    a.investigation_history.append(
        {
            "action": "cco_approve_str",
            "notes": (body.notes or "").strip() or None,
            "approved_by": approver,
            "at": a.updated_at.isoformat(),
        }
    )
    _ALERTS[alert_id] = a
    cco_details: Dict[str, Any] = {
        "approved_by": approver,
        "customer_id": a.customer_id,
        "transaction_id": a.transaction_id,
    }
    cco_notes = _audit_rationale(body.notes)
    if cco_notes:
        cco_details["notes"] = cco_notes
    audit_trail.record_event_from_user(
        user,
        action="alert.cco_approve_str",
        resource_type="alert",
        resource_id=alert_id,
        details=cco_details,
    )

    draft_report_id: Optional[str] = None
    str_notes_for_draft = (a.escalation_reason_notes or "").strip() or (
        "CCO-approved STR draft (auto-generated on approval). Compliance to finalize narrative before filing."
    )
    try:
        import app.api.v1.reports as reports_v1

        saved_notes = reports_v1.get_saved_str_draft_notes(alert_id)
        if saved_notes:
            str_notes_for_draft = saved_notes
        draft_out = await reports_v1._draft_str_report(
            request, alert_id, str_notes_for_draft, user
        )
        draft_report_id = str(draft_out.get("report_id") or "")
        r = reports_v1._REPORTS.get(draft_report_id) if draft_report_id else None
        pg = getattr(request.app.state, "pg", None)
        docx = await reports_v1.str_docx_bytes_from_report_record(r, pg=pg, user=user) if r else None
        cco = (settings.cco_email or "").strip()
        if r and docx and _smtp_configured() and cco:
            esc = (a.escalation_reason_notes or "").strip() or "—"
            subj = f"STR draft attached — alert {alert_id[:10]}… (CCO approval recorded)"
            summ = (a.summary or "").strip() or "—"
            body_txt = (
                f"Chief Compliance Officer,\n\n"
                f"You approved STR filing for alert {alert_id}.\n"
                f"Customer ID: {a.customer_id}\n"
                f"Transaction ID: {a.transaction_id}\n"
                f"Alert summary (suspicious activity in view): {summ}\n"
                f"Compliance reason for your review / escalation:\n{esc}\n\n"
                f"In the app, open CCO review and use “Show customer, occupation, suspicious transaction, and snapshot” "
                f"for the full pre-resolution package (KYC snapshot, typologies, documents).\n\n"
                f"A preliminary Suspicious Transaction Report (Word) is attached (report_id={draft_report_id}). "
                f"Compliance should refine narrative and download the latest version from Regulatory reports before filing.\n\n"
                f"Approval notes: {(body.notes or '').strip() or '—'}\n"
            )
            fname = f"STR_{draft_report_id[:8]}_CCO_draft.docx"
            await send_email_with_attachment([cco], subj, body_txt, [(fname, docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")])
    except Exception as exc:
        log.warning("cco_str_approval_draft_or_email_failed alert_id=%s err=%s", alert_id, exc)

    return {
        "alert_id": alert_id,
        "status": a.status,
        "cco_str_approved": True,
        "str_draft_report_id": draft_report_id,
        "action_key": str(uuid4()),
    }


@router.post("/{alert_id}/cco-reject")
async def cco_reject_alert(
    alert_id: str,
    body: CcoRejectBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Chief Compliance Officer rejects an alert (any non-closed, non-rejected case).
    Sets status to **rejected**, records rationale, clears CCO queue flags, notifies the compliance officer
    on the dashboard and by email when SMTP and officer_email are available.
    """
    require_cco_or_admin(user)
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _alert_visible_to_user(user, a):
        raise HTTPException(status_code=403, detail="Alert outside your zone/branch scope.")
    st = (a.status or "").lower()
    if st == "rejected":
        raise HTTPException(status_code=400, detail="This alert is already rejected.")
    if st == "closed":
        raise HTTPException(status_code=400, detail="Cannot reject a closed alert.")
    reason_raw = body.reason.strip()
    reason = _audit_rationale(reason_raw) or reason_raw
    now = datetime.utcnow()
    cco_name = str(user.get("display_name") or user.get("email") or user.get("sub") or "CCO")
    a.status = "rejected"
    a.cco_str_rejected = True
    a.cco_str_rejection_reason = reason
    a.cco_str_approved = False
    a.escalated_to_cco = False
    a.cco_otc_approved = False
    a.updated_at = now
    a.investigation_history.append(
        {
            "action": "cco_reject",
            "reason": reason,
            "rejected_by": cco_name,
            "at": now.isoformat() + "Z",
        }
    )
    _ALERTS[alert_id] = a

    co_email = _last_officer_email_from_history(a.investigation_history[:-1])
    notif_id = str(uuid4())
    email_sent = False
    email_detail = ""
    if co_email:
        push_co_notification(
            {
                "id": notif_id,
                "kind": "cco_rejection",
                "alert_id": alert_id,
                "summary": (a.summary or "")[:2000],
                "reason": reason,
                "cco_name": cco_name,
                "recipient_email": co_email.strip().lower(),
                "at": now.isoformat() + "Z",
                "read": False,
            }
        )
        if _smtp_configured():
            try:
                greet = co_email.split("@", 1)[0].replace(".", " ").title()
                subj, text = build_co_cco_rejection_email(
                    officer_greeting=greet or "Colleague",
                    alert_id=a.id,
                    customer_id=a.customer_id,
                    transaction_id=a.transaction_id,
                    summary=a.summary or "",
                    cco_name=cco_name,
                    rejection_reason=reason,
                )
                await send_plain_email([co_email.strip()], subj, text)
                email_sent = True
                email_detail = f"Email sent to {co_email}."
            except Exception as exc:
                log.warning("cco_reject_email_failed alert_id=%s err=%s", alert_id, exc)
                email_detail = f"In-app notification stored; email failed: {exc}"
        else:
            email_detail = "In-app notification stored; SMTP not configured — no email sent."
    else:
        email_detail = (
            "No compliance officer email found on prior actions (investigate / resolve / escalate / OTC filing). "
            "Rejection reason is stored on the alert for in-app review."
        )

    audit_trail.record_event_from_user(
        user,
        action="alert.cco_reject",
        resource_type="alert",
        resource_id=alert_id,
        details={
            "cco_name": cco_name,
            "customer_id": a.customer_id,
            "co_notified_email": co_email,
            "email_sent": email_sent,
        },
    )
    return {
        "alert_id": alert_id,
        "status": a.status,
        "cco_str_rejected": True,
        "cco_str_rejection_reason": reason,
        "co_notified_email": co_email,
        "email_sent": email_sent,
        "email_detail": email_detail,
        "notification_id": notif_id if co_email else None,
        "action_key": str(uuid4()),
    }


@router.post("/{alert_id}/kill-switch")
async def kill_switch(alert_id: str, body: Dict[str, Any] = None, user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    if alert_id not in _ALERTS:
        raise HTTPException(status_code=404, detail="Alert not found")
    a = _ALERTS[alert_id]
    ks_details: Dict[str, Any] = {"customer_id": a.customer_id, "transaction_id": a.transaction_id}
    if isinstance(body, dict):
        for key in ("reason", "notes", "rationale"):
            val = body.get(key)
            if val is None:
                continue
            v = _audit_rationale(val if isinstance(val, str) else str(val))
            if v:
                ks_details[key] = v
                break
    audit_trail.record_event_from_user(
        user,
        action="alert.kill_switch",
        resource_type="alert",
        resource_id=alert_id,
        details=ks_details,
    )
    return {"alert_id": alert_id, "status": "pnd_triggered", "action_key": str(uuid4())}

