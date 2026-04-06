"""Law enforcement agency (LEA) information requests with CCO pre-approval (demo workflow)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.api.v1.reports import _draft_aop_record
from app.config import settings
from app.core.security import get_current_user, require_cco_or_admin
from app.services import audit_trail
from app.services.mail_notify import (
    build_lea_cco_approval_request_email,
    build_lea_package_email,
    send_plain_email,
)
from app.services.mail_notify import _smtp_configured as smtp_configured
from app.services.statement_of_account import (
    account_context_dates_for_customer,
    clamp_statement_period,
    format_statement_text,
    parse_iso_date,
    statement_lines_for_customer,
)

router = APIRouter(prefix="/lea", tags=["lea"])

_LEA_REQUESTS: Dict[str, Dict[str, Any]] = {}

LEA_AGENCIES = frozenset({"EFCC", "POLICE", "NDLEA", "NSCDC", "ICPC", "OTHER"})


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


async def _account_context_dates(request: Request, customer_id: str) -> tuple[date, date, str]:
    pg = getattr(request.app.state, "pg", None)
    return await account_context_dates_for_customer(pg, customer_id)


def _public_rec(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Omit nothing sensitive for demo; trim only internal."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


@router.get("/agencies")
async def list_lea_agencies(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    _ = user
    return {"agencies": sorted(LEA_AGENCIES)}


@router.get("/requests/pending-cco")
async def list_pending_cco(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    require_cco_or_admin(user)
    items = [_public_rec(dict(r)) for r in _LEA_REQUESTS.values() if r.get("status") == "pending_cco"]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return {"items": items}


@router.get("/requests/{request_id}")
async def get_lea_request(request_id: str, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    rec = _LEA_REQUESTS.get(request_id)
    if not rec:
        raise HTTPException(status_code=404, detail="LEA request not found")
    role = (user.get("role") or "").strip().lower()
    sub = str(user.get("sub") or user.get("email") or "")
    created_by = str(rec.get("created_by_sub") or "")
    if role not in ("admin", "chief_compliance_officer") and created_by != sub:
        raise HTTPException(status_code=403, detail="Not allowed to view this request.")
    return _public_rec(dict(rec))


@router.post("/requests")
async def create_lea_request(
    request: Request,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    customer_id = str(payload.get("customer_id") or "").strip()
    if not customer_id:
        raise HTTPException(status_code=400, detail="customer_id is required")
    agency = str(payload.get("agency") or "").strip().upper()
    if agency not in LEA_AGENCIES:
        raise HTTPException(
            status_code=400,
            detail=f"agency must be one of: {', '.join(sorted(LEA_AGENCIES))}",
        )
    recipient_email = str(payload.get("recipient_email") or "").strip().lower()
    if not recipient_email or "@" not in recipient_email:
        raise HTTPException(status_code=400, detail="recipient_email is required")

    acc_start, acc_end, opened_s = await _account_context_dates(request, customer_id)
    p_from = parse_iso_date(payload.get("period_start")) if payload.get("period_start") else None
    p_to = parse_iso_date(payload.get("period_end")) if payload.get("period_end") else None
    d_from, d_to = clamp_statement_period(acc_start, acc_end, p_from, p_to)

    include_aop = bool(payload.get("include_aop", True))
    workstation_mac = str(payload.get("workstation_mac") or "").strip()
    internal_notes = str(payload.get("internal_notes") or "").strip()
    client_public_ip = str(payload.get("client_public_ip") or "").strip()
    if len(client_public_ip) > 64:
        client_public_ip = client_public_ip[:64]

    rid = str(uuid4())
    now = datetime.utcnow().isoformat() + "Z"
    analyst = str(user.get("display_name") or user.get("email") or user.get("sub") or "Compliance")
    rec: Dict[str, Any] = {
        "id": rid,
        "status": "draft",
        "customer_id": customer_id,
        "agency": agency,
        "period_start": d_from.isoformat(),
        "period_end": d_to.isoformat(),
        "account_opened_kyc": opened_s,
        "account_context_start": acc_start.isoformat(),
        "recipient_email": recipient_email,
        "include_aop": include_aop,
        "workstation_mac": workstation_mac,
        "internal_notes": internal_notes,
        "requester_ip": _client_ip(request),
        "client_public_ip": client_public_ip or None,
        "created_by_sub": str(user.get("sub") or user.get("email") or ""),
        "created_by_email": str(user.get("email") or user.get("sub") or ""),
        "created_at": now,
        "approved_by": None,
        "approved_at": None,
        "aop_report_id": None,
        "sent_at": None,
    }
    _LEA_REQUESTS[rid] = rec
    audit_trail.record_event_from_user(
        user,
        action="lea.request_created",
        resource_type="lea_request",
        resource_id=rid,
        details={"agency": agency, "customer_id": customer_id},
    )

    submit = bool(payload.get("submit_for_cco"))
    if submit:
        await _notify_cco_for_lea(request, rec, user, analyst)

    return _public_rec(dict(_LEA_REQUESTS[rid]))


async def _notify_cco_for_lea(request: Request, rec: Dict[str, Any], user: Dict[str, Any], analyst: str) -> None:
    rid = str(rec["id"])
    if rec.get("status") not in ("draft", "pending_cco"):
        raise HTTPException(status_code=400, detail="Request cannot be submitted for CCO approval in its current state.")
    if not smtp_configured():
        raise HTTPException(
            status_code=503,
            detail="SMTP not configured. Set SMTP_HOST, SMTP_FROM_EMAIL, and related variables to notify the CCO.",
        )
    cco = (settings.cco_email or "").strip()
    if not cco:
        raise HTTPException(status_code=503, detail="CCO_EMAIL is not set.")

    subj, text = build_lea_cco_approval_request_email(
        cco_name_or_role="Chief Compliance Officer",
        request_id=rid,
        agency=str(rec["agency"]),
        customer_id=str(rec["customer_id"]),
        period_start=str(rec["period_start"]),
        period_end=str(rec["period_end"]),
        recipient_email=str(rec["recipient_email"]),
        include_aop=bool(rec.get("include_aop")),
        analyst=analyst,
        internal_notes=str(rec.get("internal_notes") or ""),
        requester_ip=str(rec.get("requester_ip") or ""),
        client_public_ip=str(rec.get("client_public_ip") or ""),
    )
    await send_plain_email([cco], subj, text)
    rec["status"] = "pending_cco"
    rec["cco_notified_at"] = datetime.utcnow().isoformat() + "Z"
    _LEA_REQUESTS[rid] = rec
    audit_trail.record_event_from_user(
        user,
        action="lea.cco_notified",
        resource_type="lea_request",
        resource_id=rid,
        details={"to": cco},
    )


@router.post("/requests/{request_id}/notify-cco")
async def notify_cco_lea(
    request_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    rec = _LEA_REQUESTS.get(request_id)
    if not rec:
        raise HTTPException(status_code=404, detail="LEA request not found")
    analyst = str(user.get("display_name") or user.get("email") or user.get("sub") or "Compliance")
    await _notify_cco_for_lea(request, rec, user, analyst)
    return _public_rec(dict(_LEA_REQUESTS[request_id]))


@router.post("/requests/{request_id}/cco-approve")
async def cco_approve_lea(
    request_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    require_cco_or_admin(user)
    rec = _LEA_REQUESTS.get(request_id)
    if not rec:
        raise HTTPException(status_code=404, detail="LEA request not found")
    if rec.get("status") != "pending_cco":
        raise HTTPException(status_code=400, detail="Only requests pending CCO approval can be approved.")
    notes = ""
    if isinstance(body.get("notes"), str):
        notes = body["notes"].strip()
    approver = str(user.get("display_name") or user.get("email") or user.get("sub") or "CCO")
    now = datetime.utcnow().isoformat() + "Z"
    rec["status"] = "approved"
    rec["approved_by"] = approver
    rec["approved_at"] = now
    if notes:
        rec["cco_notes"] = notes
    _LEA_REQUESTS[request_id] = rec
    audit_trail.record_event_from_user(
        user,
        action="lea.cco_approved",
        resource_type="lea_request",
        resource_id=request_id,
        details={"customer_id": rec.get("customer_id"), "agency": rec.get("agency")},
    )
    return _public_rec(dict(rec))


@router.post("/requests/{request_id}/send")
async def send_lea_package(
    request_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    rec = _LEA_REQUESTS.get(request_id)
    if not rec:
        raise HTTPException(status_code=404, detail="LEA request not found")
    sub = str(user.get("sub") or user.get("email") or "")
    if str(rec.get("created_by_sub") or "") != sub:
        role = (user.get("role") or "").strip().lower()
        if role not in ("admin", "chief_compliance_officer"):
            raise HTTPException(status_code=403, detail="Only the creating officer (or admin) may send this package.")
    if rec.get("status") == "sent":
        raise HTTPException(status_code=400, detail="This package has already been sent.")
    if rec.get("status") != "approved":
        raise HTTPException(
            status_code=400,
            detail="Chief Compliance Officer approval is required before sending to the law enforcement contact.",
        )
    if not smtp_configured():
        raise HTTPException(
            status_code=503,
            detail="SMTP not configured. Set SMTP_HOST and SMTP_FROM_EMAIL to send email.",
        )

    cid = str(rec["customer_id"])
    d_from = datetime.fromisoformat(str(rec["period_start"])).date()
    d_to = datetime.fromisoformat(str(rec["period_end"])).date()
    lines = statement_lines_for_customer(cid, d_from, d_to)
    stmt = format_statement_text(lines, cid, str(rec.get("account_opened_kyc") or ""))

    aop_id: Optional[str] = None
    if rec.get("include_aop"):
        aop_out = _draft_aop_record(
            cid,
            user,
            account_product="Savings",
            risk_rating="medium",
        )
        aop_id = str(aop_out.get("report_id") or "")
        rec["aop_report_id"] = aop_id

    prepared = str(user.get("display_name") or user.get("email") or user.get("sub") or "Compliance")
    to_addr = str(rec["recipient_email"])
    subj, body_text = build_lea_package_email(
        agency=str(rec["agency"]),
        customer_id=cid,
        period_start=str(rec["period_start"]),
        period_end=str(rec["period_end"]),
        statement_text=stmt,
        aop_report_id=aop_id,
        requester_ip=str(rec.get("requester_ip") or ""),
        workstation_mac=str(rec.get("workstation_mac") or ""),
        prepared_by=prepared,
        bank_reference=request_id,
        client_public_ip=str(rec.get("client_public_ip") or ""),
    )
    await send_plain_email([to_addr], subj, body_text)

    rec["status"] = "sent"
    rec["sent_at"] = datetime.utcnow().isoformat() + "Z"
    rec["transaction_rows_sent"] = len(lines)
    _LEA_REQUESTS[request_id] = rec
    audit_trail.record_event_from_user(
        user,
        action="lea.package_sent",
        resource_type="lea_request",
        resource_id=request_id,
        details={"to": to_addr, "agency": rec.get("agency"), "rows": len(lines)},
    )
    return _public_rec(dict(rec))