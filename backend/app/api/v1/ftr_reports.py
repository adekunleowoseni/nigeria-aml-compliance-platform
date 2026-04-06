"""
Funds Transfer Report (FTR) API — CBN cross-border / wire reporting (draft, file, submit, auto-schedule).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.api.v1.in_memory_stores import _TXNS
from app.config import settings
from app.core.security import get_current_user
from app.db.postgres_client import PostgresClient
from app.models.transaction import TransactionResponse
from app.services import audit_trail
from app.services.customer_kyc_db import get_or_create_customer_kyc
from app.services.ftr_logic import (
    build_ftr_csv,
    build_ftr_xml,
    filing_deadline_for_value_date,
    is_ftr_eligible,
    load_sample_template_xml,
    map_transaction_to_party_fields,
    value_date_for_transaction,
)
from app.services.reporting_profile_db import get_reporting_profile_row
from app.services.ftr_reports_db import (
    ensure_ftr_reports_schema,
    get_ftr_by_id,
    get_ftr_by_transaction,
    get_schedule,
    insert_ftr,
    list_ftrs as ftr_db_list,
    mark_ftr_submitted,
    next_report_ref,
    touch_schedule_last_run,
    update_ftr_draft,
    upsert_schedule,
)
from app.services.regulatory_reports import minimal_docx_bytes

router = APIRouter(prefix="/reports/ftr", tags=["reports", "ftr"])


async def _ftr_reporting_entity_name(pg: PostgresClient) -> str:
    try:
        row = await get_reporting_profile_row(pg)
        n = (row.get("reporting_entity_name") or "").strip()
        return n or "Reporting Institution"
    except Exception:
        return "Reporting Institution"


class FtrGenerateError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(message or code)


def _require_admin(user: Dict[str, Any]) -> None:
    if (user.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _thresholds_from_settings() -> tuple[float, float, float]:
    return (
        float(settings.ftr_threshold_ngn),
        float(settings.ftr_threshold_usd),
        float(settings.ftr_usd_ngn_rate),
    )


def _thresholds_from_schedule(sch: Dict[str, Any]) -> tuple[float, float, float]:
    return (
        float(sch.get("threshold_ngn") or settings.ftr_threshold_ngn),
        float(sch.get("threshold_usd") or settings.ftr_threshold_usd),
        float(sch.get("usd_ngn_rate") or settings.ftr_usd_ngn_rate),
    )


async def _generate_ftr_core(
    pg: PostgresClient,
    txn: TransactionResponse,
    *,
    created_by: str,
    threshold_ngn: float,
    threshold_usd: float,
    usd_ngn_rate: float,
    skip_eligibility: bool = False,
) -> Dict[str, Any]:
    td = txn.model_dump()
    if not skip_eligibility:
        ok, reason = is_ftr_eligible(
            td,
            threshold_ngn=threshold_ngn,
            threshold_usd=threshold_usd,
            usd_ngn_rate=usd_ngn_rate,
        )
        if not ok:
            raise FtrGenerateError("not_eligible", f"transaction_not_eligible:{reason}")

    existing = await get_ftr_by_transaction(pg, txn.id)
    if existing:
        raise FtrGenerateError("duplicate", "ftr_already_exists_for_transaction")

    kyc = await get_or_create_customer_kyc(pg, txn.customer_id, td)
    parties = map_transaction_to_party_fields(td, kyc)
    vd = value_date_for_transaction(td)
    fd = filing_deadline_for_value_date(vd)
    ref = await next_report_ref(pg, day=datetime.now(timezone.utc).date())

    return await insert_ftr(
        pg,
        report_ref=ref,
        transaction_id=txn.id,
        customer_id=txn.customer_id,
        originator_name=parties.get("originator_name"),
        originator_account=parties.get("originator_account"),
        originator_address=parties.get("originator_address"),
        originator_country=parties.get("originator_country"),
        beneficiary_name=parties.get("beneficiary_name"),
        beneficiary_account=parties.get("beneficiary_account"),
        beneficiary_bank_bic=parties.get("beneficiary_bank_bic"),
        beneficiary_country=parties.get("beneficiary_country"),
        amount=float(txn.amount),
        currency=(txn.currency or "NGN").strip()[:3],
        value_date=vd,
        payment_reference=parties.get("payment_reference"),
        filing_deadline=fd,
        created_by=created_by,
    )


# --- Static paths before /{ftr_id} ---


class FtrScheduleBody(BaseModel):
    enabled: Optional[bool] = None
    frequency: Optional[str] = Field(None, description="daily")
    threshold_ngn: Optional[float] = None
    threshold_usd: Optional[float] = None
    usd_ngn_rate: Optional[float] = None


@router.get("/schedule")
async def get_ftr_schedule(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    """Admin: read auto-generation schedule and thresholds."""
    _require_admin(user)
    sch = await get_schedule(request.app.state.pg)
    return {
        **sch,
        "retention_years": settings.ftr_retention_years,
        "scan_interval_hours": settings.ftr_auto_scan_interval_hours,
    }


@router.post("/schedule")
async def post_ftr_schedule(
    request: Request,
    body: FtrScheduleBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(user)
    sch = await upsert_schedule(
        request.app.state.pg,
        enabled=body.enabled,
        frequency=body.frequency,
        threshold_ngn=body.threshold_ngn,
        threshold_usd=body.threshold_usd,
        usd_ngn_rate=body.usd_ngn_rate,
    )
    audit_trail.record_event_from_user(
        user,
        action="admin.ftr.schedule_updated",
        resource_type="configuration",
        resource_id="ftr_auto_schedule",
        details=sch,
    )
    return {"status": "ok", "schedule": sch}


@router.post("/scan/run")
async def run_ftr_scan_manual(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    """Admin: run auto-generation scan immediately (ignores schedule enabled / daily throttle)."""
    _require_admin(user)
    return await run_scheduled_ftr_scan(request.app, force=True)


@router.post("/generate/{transaction_id}")
async def generate_ftr_draft(
    request: Request,
    transaction_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    force: bool = Query(False, description="If true, skip eligibility check (admin override; demo only)."),
):
    txn = _TXNS.get(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="transaction_not_found")
    if force:
        _require_admin(user)
    tn, tu, tr = _thresholds_from_settings()
    pg = request.app.state.pg
    try:
        row = await _generate_ftr_core(
            pg,
            txn,
            created_by=str(user.get("email") or user.get("sub") or "unknown"),
            threshold_ngn=tn,
            threshold_usd=tu,
            usd_ngn_rate=tr,
            skip_eligibility=force,
        )
    except FtrGenerateError as e:
        if e.code == "not_eligible":
            raise HTTPException(status_code=400, detail=e.message) from e
        if e.code == "duplicate":
            raise HTTPException(status_code=409, detail=e.message) from e
        raise HTTPException(status_code=400, detail=e.message) from e
    audit_trail.record_event_from_user(
        user,
        action="report.ftr.generated",
        resource_type="ftr_report",
        resource_id=str(row.get("report_ref") or ""),
        details={"ftr_id": str(row.get("id")), "transaction_id": transaction_id},
    )
    return {"status": "ok", "ftr": row, "retention_years": settings.ftr_retention_years}


@router.get("")
async def list_ftr_reports(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    status: Optional[str] = Query(None, description="DRAFT, SUBMITTED, ACKNOWLEDGED, REJECTED"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    rows, total = await ftr_db_list(
        request.app.state.pg,
        from_date=from_date,
        to_date=to_date,
        status=status,
        skip=skip,
        limit=limit,
    )
    return {
        "items": rows,
        "total": total,
        "skip": skip,
        "limit": limit,
        "retention_years": settings.ftr_retention_years,
    }


class FtrDraftPatch(BaseModel):
    originator_name: Optional[str] = None
    originator_account: Optional[str] = None
    originator_address: Optional[str] = None
    originator_country: Optional[str] = None
    beneficiary_name: Optional[str] = None
    beneficiary_account: Optional[str] = None
    beneficiary_bank_bic: Optional[str] = None
    beneficiary_country: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = Field(None, max_length=3)
    value_date: Optional[str] = None
    payment_reference: Optional[str] = None


@router.get("/{ftr_id}/file")
async def download_ftr_file(
    request: Request,
    ftr_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    format: str = Query("xml", description="xml, csv, or docx"),
):
    row = await get_ftr_by_id(request.app.state.pg, ftr_id)
    if not row:
        raise HTTPException(status_code=404, detail="ftr_not_found")
    fmt = format.lower().strip()
    if fmt == "xml":
        ent = await _ftr_reporting_entity_name(request.app.state.pg)
        xml = build_ftr_xml(row, reporting_entity_name=ent)
        return Response(
            content=xml.encode("utf-8"),
            media_type="application/xml; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{row.get("report_ref") or "ftr"}.xml"'},
        )
    if fmt == "csv":
        body = build_ftr_csv([row])
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{row.get("report_ref") or "ftr"}.csv"'},
        )
    if fmt == "docx":
        lines = [
            f"FTR {row.get('report_ref')}",
            f"Transaction: {row.get('transaction_id')}",
            f"Customer: {row.get('customer_id')}",
            f"Value date: {row.get('value_date')} | Deadline: {row.get('filing_deadline')}",
            f"Amount: {row.get('amount')} {row.get('currency')}",
            f"Originator: {row.get('originator_name')} / {row.get('originator_account')}",
            f"Beneficiary: {row.get('beneficiary_name')} / {row.get('beneficiary_account')} BIC {row.get('beneficiary_bank_bic')}",
            f"Status: {row.get('filing_status')}",
        ]
        doc = minimal_docx_bytes(f"FTR {row.get('report_ref')}", "\n\n".join(lines))
        return Response(
            content=doc,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{row.get("report_ref") or "ftr"}.docx"'},
        )
    raise HTTPException(status_code=400, detail="format must be xml, csv, or docx")


@router.patch("/{ftr_id}")
async def patch_ftr_draft(
    request: Request,
    ftr_id: str,
    body: FtrDraftPatch,
    user: Dict[str, Any] = Depends(get_current_user),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    row = await update_ftr_draft(request.app.state.pg, ftr_id, fields)
    if not row:
        raise HTTPException(status_code=404, detail="ftr_not_found_or_not_draft")
    audit_trail.record_event_from_user(
        user,
        action="report.ftr.draft_updated",
        resource_type="ftr_report",
        resource_id=str(row.get("report_ref") or ""),
        details={"ftr_id": ftr_id, "fields": list(fields.keys())},
    )
    return {"status": "ok", "ftr": row}


@router.get("/{ftr_id}")
async def get_ftr_detail(
    request: Request,
    ftr_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    row = await get_ftr_by_id(request.app.state.pg, ftr_id)
    if not row:
        raise HTTPException(status_code=404, detail="ftr_not_found")
    return {
        "ftr": row,
        "sample_template_xml": load_sample_template_xml(),
        "retention_years": settings.ftr_retention_years,
        "retention_note": (
            f"Retain FTR records and filed XML for at least {settings.ftr_retention_years} years "
            "or per institution policy and CBN direction."
        ),
        "download_formats": ["xml", "csv", "docx"],
    }


@router.post("/{ftr_id}/submit")
async def submit_ftr(
    request: Request,
    ftr_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg = request.app.state.pg
    row = await get_ftr_by_id(pg, ftr_id)
    if not row:
        raise HTTPException(status_code=404, detail="ftr_not_found")
    if (row.get("filing_status") or "").upper() != "DRAFT":
        raise HTTPException(status_code=400, detail="only_draft_can_be_submitted")

    ent = await _ftr_reporting_entity_name(pg)
    xml_body = build_ftr_xml(row, reporting_entity_name=ent)
    mode = (settings.cbn_ftr_submit_mode or "stub").strip().lower()
    ack: Optional[str] = None
    if mode == "file_drop" and (settings.cbn_ftr_file_drop_dir or "").strip():
        drop = Path(settings.cbn_ftr_file_drop_dir.strip())
        drop.mkdir(parents=True, exist_ok=True)
        fn = f"{row.get('report_ref') or ftr_id}.xml"
        target = drop / fn
        target.write_text(xml_body, encoding="utf-8")
        ack = f"FILE:{target.as_posix()}"
    elif mode == "api" and (settings.cbn_ftr_api_url or "").strip():
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                r = await client.post(
                    settings.cbn_ftr_api_url.strip(),
                    content=xml_body.encode("utf-8"),
                    headers={"Content-Type": "application/xml"},
                )
                r.raise_for_status()
                ack = r.headers.get("X-CBN-Ack") or r.headers.get("X-Reference")
                if not ack and r.text:
                    ack = r.text.strip()[:200]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"cbn_api_submit_failed:{exc!s}") from exc
    elif mode == "file_drop":
        raise HTTPException(status_code=400, detail="cbn_ftr_file_drop_dir_not_configured")
    else:
        ack = f"CBN-STUB-{uuid4()}"

    updated = await mark_ftr_submitted(pg, ftr_id, cbn_ack=ack)
    if not updated:
        raise HTTPException(status_code=400, detail="submit_failed")
    audit_trail.record_event_from_user(
        user,
        action="report.ftr.submitted",
        resource_type="ftr_report",
        resource_id=str(updated.get("report_ref") or ""),
        details={
            "ftr_id": ftr_id,
            "transaction_id": updated.get("transaction_id"),
            "cbn_acknowledgment_ref": ack,
            "submit_mode": mode,
        },
    )
    return {"status": "ok", "ftr": updated}


async def run_scheduled_ftr_scan(app: Any, *, force: bool = False) -> Dict[str, Any]:
    """Background / manual: create FTR drafts for eligible transactions that lack one."""
    pg = getattr(getattr(app, "state", None), "pg", None)
    if pg is None:
        return {"ran": False, "reason": "no_postgres"}
    await ensure_ftr_reports_schema(pg)
    sch = await get_schedule(pg)
    if not force and not sch.get("enabled"):
        return {"ran": False, "reason": "schedule_disabled", "created": 0}
    freq = str(sch.get("frequency") or "daily").lower()
    last_run = sch.get("last_run_at")
    if not force and freq == "daily" and last_run:
        lr = last_run
        if isinstance(lr, str):
            try:
                lr = datetime.fromisoformat(lr.replace("Z", "+00:00"))
            except ValueError:
                lr = None
        if isinstance(lr, datetime):
            if lr.tzinfo is None:
                lr = lr.replace(tzinfo=timezone.utc)
            today = datetime.now(timezone.utc).date()
            if lr.astimezone(timezone.utc).date() == today:
                return {"ran": False, "reason": "already_ran_today", "created": 0}

    tn, tu, tr = _thresholds_from_schedule(sch)
    created: List[str] = []
    for txn in list(_TXNS.values()):
        td = txn.model_dump()
        ok, _ = is_ftr_eligible(td, threshold_ngn=tn, threshold_usd=tu, usd_ngn_rate=tr)
        if not ok:
            continue
        ex = await get_ftr_by_transaction(pg, txn.id)
        if ex:
            continue
        try:
            row = await _generate_ftr_core(
                pg,
                txn,
                created_by="system:ftr-auto-scan",
                threshold_ngn=tn,
                threshold_usd=tu,
                usd_ngn_rate=tr,
                skip_eligibility=True,
            )
            created.append(str(row.get("report_ref")))
            audit_trail.record_event(
                action="report.ftr.auto_generated",
                resource_type="ftr_report",
                resource_id=str(row.get("report_ref") or ""),
                actor_sub="system",
                actor_email="system",
                actor_role="system",
                details={"transaction_id": txn.id, "ftr_id": str(row.get("id"))},
            )
        except FtrGenerateError:
            continue

    await touch_schedule_last_run(pg)
    return {"ran": True, "created": len(created), "report_refs": created}
