from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import settings
from app.core.security import get_current_user
from app.models.alert import (
    AlertResponse,
    CcoActionNotificationRequest,
    EddNotificationRequest,
    EscalationRequest,
    InvestigationRequest,
    ResolutionRequest,
)
from app.services.alert_snapshot import build_alert_snapshot
from app.services.mail_notify import (
    build_cco_action_notification_email,
    build_edd_request_email,
    send_plain_email,
    _smtp_configured,
)

router = APIRouter(prefix="/alerts")

_ALERTS: Dict[str, AlertResponse] = {}


def _seed_if_empty() -> None:
    """Disabled: demo data comes from /demo/seed or /demo/simulate-temporal only."""
    return


@router.get("/", response_model=Dict[str, Any])
async def list_alerts(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    severity: Optional[str] = None,
    status: Optional[str] = None,
    date_range: Optional[str] = None,
    assigned_to: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _seed_if_empty()
    items = list(_ALERTS.values())
    if status:
        items = [a for a in items if a.status == status]
    total = len(items)
    return {"items": items[skip : skip + limit], "total": total, "skip": skip, "limit": limit}


@router.get("/search", response_model=Dict[str, Any])
async def search_alerts(
    q: str,
    skip: int = 0,
    limit: int = 20,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _seed_if_empty()
    ql = q.lower()
    items = [a for a in _ALERTS.values() if (a.summary or "").lower().find(ql) >= 0 or a.customer_id.lower().find(ql) >= 0]
    total = len(items)
    return {"items": items[skip : skip + limit], "total": total, "skip": skip, "limit": limit}


@router.get("/dashboard")
async def dashboard(user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    counts_by_severity = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    counts_by_status: Dict[str, int] = {}
    for a in _ALERTS.values():
        if a.severity >= 0.9:
            counts_by_severity["critical"] += 1
        elif a.severity >= 0.75:
            counts_by_severity["high"] += 1
        elif a.severity >= 0.5:
            counts_by_severity["medium"] += 1
        else:
            counts_by_severity["low"] += 1
        counts_by_status[a.status] = counts_by_status.get(a.status, 0) + 1

    # minimal trend series for UI
    today = datetime.utcnow().date()
    trend_over_time: List[Dict[str, Any]] = []
    for d in range(29, -1, -1):
        date = today - timedelta(days=d)
        trend_over_time.append({"date": date.isoformat(), "critical": 0, "high": 0, "medium": 0, "low": 0})
    return {
        "counts_by_severity": counts_by_severity,
        "counts_by_status": counts_by_status,
        "trend_over_time": trend_over_time,
        "average_resolution_time_hours": None,
    }


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    return a


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
    from app.api.v1 import transactions as txmod

    txn = txmod._TXNS.get(a.transaction_id)
    txn_dict = txn.model_dump() if txn else None
    all_tx = [t.model_dump() for t in txmod._TXNS.values()]
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
    from app.api.v1 import transactions as txmod

    txn = txmod._TXNS.get(a.transaction_id)
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
    a.investigation_history.append(
        {"action": "investigate", "investigator_id": body.investigator_id, "notes": body.notes, "at": a.updated_at.isoformat()}
    )
    _ALERTS[alert_id] = a
    return {"alert_id": alert_id, "status": a.status, "investigator_id": body.investigator_id, "action_key": str(uuid4())}


@router.post("/{alert_id}/resolve")
async def resolve(alert_id: str, body: ResolutionRequest, user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    a.status = "closed"
    a.updated_at = datetime.utcnow()
    a.investigation_history.append(
        {
            "action": "resolve",
            "resolution": body.resolution,
            "notes": body.notes,
            "action_taken": body.action_taken,
            "at": a.updated_at.isoformat(),
        }
    )
    _ALERTS[alert_id] = a
    return {"alert_id": alert_id, "resolution": body.resolution, "status": a.status, "action_key": str(uuid4())}


@router.post("/{alert_id}/escalate")
async def escalate(alert_id: str, body: EscalationRequest, user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    a = _ALERTS.get(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    a.status = "investigating"
    a.updated_at = datetime.utcnow()
    a.investigation_history.append(
        {"action": "escalate", "reason": body.reason, "escalated_to": body.escalated_to, "at": a.updated_at.isoformat()}
    )
    _ALERTS[alert_id] = a
    return {"alert_id": alert_id, "status": a.status, "escalated_to": body.escalated_to, "action_key": str(uuid4())}


@router.post("/{alert_id}/kill-switch")
async def kill_switch(alert_id: str, body: Dict[str, Any] = None, user: Dict[str, Any] = Depends(get_current_user)):
    _seed_if_empty()
    if alert_id not in _ALERTS:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"alert_id": alert_id, "status": "pnd_triggered", "action_key": str(uuid4())}

