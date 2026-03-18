from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.security import get_current_user
from app.models.alert import (
    AlertResponse,
    EscalationRequest,
    InvestigationRequest,
    ResolutionRequest,
)

router = APIRouter(prefix="/alerts")

_ALERTS: Dict[str, AlertResponse] = {}


def _seed_if_empty() -> None:
    if _ALERTS:
        return
    now = datetime.utcnow()
    for i in range(12):
        aid = str(uuid4())
        _ALERTS[aid] = AlertResponse(
            id=aid,
            transaction_id=str(uuid4()),
            customer_id=f"CUST-NG-{9000+i}",
            severity=min(1.0, 0.2 + (i / 12.0)),
            status="open",
            rule_ids=["RULE-ANOMALY"],
            summary="Anomalous transaction pattern detected",
            created_at=now - timedelta(hours=i * 3),
        )


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

