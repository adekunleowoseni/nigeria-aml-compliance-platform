"""Board / ECO / Management MI packs and email schedules (CBN)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from croniter import croniter as croniter_mod
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.api.v1.reports import _REPORTS
from app.config import settings
from app.core.security import bearer_scheme, get_current_user, get_current_user_or_mi_internal, require_admin, _decode_token
from app.services import audit_trail
from app.services.board_pack_pdf import build_board_pack_pdf_bytes
from app.services.mi_executive_service import (
    build_board_pack_payload,
    build_eco_dashboard_payload,
    build_management_exceptions_payload,
)
from app.services.mi_pdf_token import sign_board_pdf_download, verify_board_pdf_token
from app.services.mi_report_schedules_db import (
    ensure_mi_schedule_schema,
    insert_schedule,
    list_schedules,
    set_paused,
)
from app.services.mi_schedule_runner import run_due_mi_schedules
from app.services.mi_word_export import build_board_pack_docx_bytes

router = APIRouter(prefix="/reports", tags=["reports", "mi"])


def _role(user: Dict[str, Any]) -> str:
    return (user.get("role") or "").strip().lower()


def _require_board(user: Dict[str, Any]) -> None:
    if _role(user) not in ("admin", "chief_compliance_officer"):
        raise HTTPException(status_code=403, detail="Board pack requires Administrator or Chief Compliance Officer.")


def _require_eco(user: Dict[str, Any]) -> None:
    if _role(user) not in ("admin", "chief_compliance_officer", "compliance_officer"):
        raise HTTPException(status_code=403, detail="ECO dashboard requires compliance role.")


def _require_mgmt(user: Dict[str, Any]) -> None:
    _require_eco(user)


def _public_base(request: Request) -> str:
    b = (settings.public_api_base_url or "").strip().rstrip("/")
    if b:
        return b
    return str(request.base_url).rstrip("/")


@router.get("/board/pack")
async def board_aml_pack(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    _require_board(user)
    pg = request.app.state.pg
    payload = await build_board_pack_payload(user, pg=pg, _reports=_REPORTS)
    try:
        from pathlib import Path

        title_path = Path(__file__).resolve().parent.parent.parent.parent / "templates" / "reports" / "board_pack_title.txt"
        if title_path.is_file():
            payload["template_title"] = title_path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    token, exp = sign_board_pdf_download(ttl_seconds=int(settings.mi_pdf_download_ttl_seconds))
    base = _public_base(request)
    pdf_url = f"{base}/api/v1/reports/board/pack.pdf?token={token}"
    word_url = f"{base}/api/v1/reports/board/pack.docx?token={token}"
    audit_trail.record_event_from_user(
        user,
        action="mi_report.board_pack_viewed",
        resource_type="mi_board_pack",
        resource_id="current",
        details={"pdf_expires_at": exp},
    )
    return {
        **payload,
        "pdf_download_url": pdf_url,
        "word_download_url": word_url,
        "pdf_expires_at": exp,
        "charts_count": len(payload.get("charts") or []),
    }


async def _board_pack_payload_for_download(request: Request, token: Optional[str], creds: Optional[HTTPAuthorizationCredentials]):
    pg = request.app.state.pg
    if token:
        if not verify_board_pdf_token(token):
            raise HTTPException(status_code=401, detail="Invalid or expired download token.")
        payload_data = await build_board_pack_payload(
            {"role": "admin", "sub": "pdf-token", "email": "pdf-viewer@token"},
            pg=pg,
            _reports=_REPORTS,
        )
        audit_trail.record_event(
            action="mi_report.board_pack_download_token",
            resource_type="mi_board_pack",
            resource_id="token",
            actor_sub="pdf-token",
            actor_email="pdf-viewer@token",
            actor_role="system",
            details={},
        )
        return payload_data
    if creds is None:
        raise HTTPException(status_code=401, detail="Provide ?token= from pack JSON or Bearer authentication.")
    user = _decode_token(creds.credentials)
    _require_board(user)
    payload_data = await build_board_pack_payload(user, pg=pg, _reports=_REPORTS)
    audit_trail.record_event_from_user(
        user,
        action="mi_report.board_pack_pdf_download",
        resource_type="mi_board_pack",
        resource_id="current",
        details={},
    )
    return payload_data


@router.get("/board/pack.pdf")
async def board_aml_pack_pdf(
    request: Request,
    token: Optional[str] = Query(None),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    """HMAC token (from board pack JSON) or authenticated Board viewer."""
    payload_data = await _board_pack_payload_for_download(request, token, creds)
    pdf = build_board_pack_pdf_bytes(payload_data)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="Board_AML_Pack.pdf"'},
    )


@router.get("/board/pack.docx")
async def board_aml_pack_docx(
    request: Request,
    token: Optional[str] = Query(None),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    payload_data = await _board_pack_payload_for_download(request, token, creds)
    docx = build_board_pack_docx_bytes(payload_data)
    return Response(
        content=docx,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="Board_AML_Pack.docx"'},
    )


@router.get("/eco/dashboard")
async def eco_dashboard(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    _require_eco(user)
    pg = request.app.state.pg
    payload = await build_eco_dashboard_payload(user, pg=pg)
    audit_trail.record_event_from_user(
        user,
        action="mi_report.eco_dashboard_viewed",
        resource_type="mi_eco",
        resource_id="current",
        details={},
    )
    return JSONResponse(
        content=payload,
        headers={
            "Cache-Control": "public, max-age=300",
            "X-MI-Refresh-Seconds": "300",
        },
    )


@router.get("/management/exceptions")
async def management_exceptions(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    _require_mgmt(user)
    payload = build_management_exceptions_payload(user)
    audit_trail.record_event_from_user(
        user,
        action="mi_report.management_exceptions_viewed",
        resource_type="mi_management",
        resource_id="current",
        details={},
    )
    return payload


class MiScheduleCreate(BaseModel):
    report_type: str = Field(..., description="board_aml_pack | eco_dashboard | management_exceptions")
    cron_expression: str = Field(..., min_length=9, max_length=128, description="5-field cron, UTC")
    recipients: List[str] = Field(default_factory=list, max_length=50)
    is_paused: bool = False


class MiSchedulePauseBody(BaseModel):
    is_paused: bool


@router.post("/schedule")
async def create_mi_schedule(request: Request, body: MiScheduleCreate, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    if not croniter_mod.is_valid(body.cron_expression.strip()):
        raise HTTPException(status_code=400, detail="Invalid cron_expression (5-field, UTC).")
    pg = request.app.state.pg
    await ensure_mi_schedule_schema(pg)
    actor = str(user.get("email") or user.get("sub") or "admin")
    row = await insert_schedule(
        pg,
        report_type=body.report_type.strip().lower(),
        cron_expression=body.cron_expression.strip(),
        recipients=[str(x).strip() for x in body.recipients if str(x).strip()],
        is_paused=body.is_paused,
        updated_by=actor,
    )
    audit_trail.record_event_from_user(
        user,
        action="mi_report.schedule_created",
        resource_type="mi_schedule",
        resource_id=str(row.get("id") or ""),
        details={"report_type": body.report_type, "cron": body.cron_expression},
    )
    return {"status": "ok", "schedule": row}


@router.get("/schedule")
async def list_mi_schedules(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    pg = request.app.state.pg
    await ensure_mi_schedule_schema(pg)
    return {"items": await list_schedules(pg)}


@router.patch("/schedule/{schedule_id}")
async def pause_resume_schedule(
    request: Request,
    schedule_id: str,
    body: MiSchedulePauseBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    pg = request.app.state.pg
    await ensure_mi_schedule_schema(pg)
    actor = str(user.get("email") or user.get("sub") or "admin")
    ok = await set_paused(pg, schedule_id, body.is_paused, actor)
    if not ok:
        raise HTTPException(status_code=404, detail="schedule_not_found")
    audit_trail.record_event_from_user(
        user,
        action="mi_report.schedule_paused" if body.is_paused else "mi_report.schedule_resumed",
        resource_type="mi_schedule",
        resource_id=schedule_id,
        details={"is_paused": body.is_paused},
    )
    return {"status": "ok", "schedule_id": schedule_id, "is_paused": body.is_paused}


@router.post("/mi/tick-schedules")
async def tick_mi_schedules(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user_or_mi_internal),
):
    """Celery Beat: fire due schedules (SMTP + audit). ``X-MI-Internal-Key`` or admin JWT."""
    require_admin(user)
    pg = request.app.state.pg
    await ensure_mi_schedule_schema(pg)
    out = await run_due_mi_schedules(pg, actor_email=str(user.get("email") or "mi-tick"))
    return {"status": "ok", **out}

