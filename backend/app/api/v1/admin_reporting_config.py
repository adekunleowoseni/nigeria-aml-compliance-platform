"""Admin: institution reporting profile (CBN / bank templates) + regulatory return calendar."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.security import get_current_user, require_admin
from app.services import audit_trail
from app.services.reporting_context import (
    TEMPLATE_PACK_PRESETS,
    effective_default_outputs,
    upcoming_calendar_preview,
)
from app.services.reporting_profile_db import (
    delete_calendar_entry,
    ensure_reporting_profile_schema,
    get_reporting_profile_row,
    insert_calendar_entry,
    list_calendar_entries,
    update_calendar_entry,
    upsert_reporting_profile,
    VALID_FREQUENCIES,
)

router = APIRouter(prefix="/admin/reporting", tags=["admin", "reporting"])


@router.get("/template-packs")
async def list_template_packs(user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    return {
        "packs": [
            {
                "id": "cbn_default",
                "label": "CBN-aligned (generic licensed FI)",
                "defaults": TEMPLATE_PACK_PRESETS["cbn_default"],
            },
            {
                "id": "gtbank",
                "label": "GTBank-style preset",
                "defaults": TEMPLATE_PACK_PRESETS["gtbank"],
            },
            {
                "id": "zenith",
                "label": "Zenith Bank-style preset",
                "defaults": TEMPLATE_PACK_PRESETS["zenith"],
            },
            {
                "id": "uba",
                "label": "UBA-style preset",
                "defaults": TEMPLATE_PACK_PRESETS["uba"],
            },
            {
                "id": "access",
                "label": "Access Bank-style preset",
                "defaults": TEMPLATE_PACK_PRESETS["access"],
            },
            {"id": "custom", "label": "Custom (manual entity names)", "defaults": {}},
        ]
    }


@router.get("/profile")
async def get_reporting_profile(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    pg = request.app.state.pg
    await ensure_reporting_profile_schema(pg)
    row = await get_reporting_profile_row(pg)
    eff = effective_default_outputs(row.get("default_outputs"))
    return {
        "profile": row,
        "default_outputs_effective": eff,
        "template_pack_presets": TEMPLATE_PACK_PRESETS,
    }


class ReportingProfilePut(BaseModel):
    template_pack: str = Field(..., description="cbn_default | gtbank | zenith | uba | access | custom")
    institution_display_name: str = Field(..., min_length=2, max_length=500)
    reporting_entity_name: str = Field(..., min_length=2, max_length=500)
    entity_registration_ref: str = Field(..., min_length=2, max_length=200)
    default_outputs: Dict[str, Any] = Field(default_factory=dict)
    narrative_style: str = Field(default="cbn_formal", description="cbn_formal | bank_standard | concise")
    apply_preset_defaults: bool = Field(
        default=False,
        description="If true, merge template_pack preset into name fields before save (custom ignored).",
    )


@router.put("/profile")
async def put_reporting_profile(
    request: Request,
    body: ReportingProfilePut,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    pg = request.app.state.pg
    await ensure_reporting_profile_schema(pg)
    pack = body.template_pack.strip().lower()
    inst = body.institution_display_name.strip()
    rent = body.reporting_entity_name.strip()
    reg = body.entity_registration_ref.strip()
    if body.apply_preset_defaults and pack != "custom" and pack in TEMPLATE_PACK_PRESETS:
        pr = TEMPLATE_PACK_PRESETS[pack]
        inst = pr.get("institution_display_name", inst)
        rent = pr.get("reporting_entity_name", rent)
        reg = pr.get("entity_registration_ref", reg)
    actor = str(user.get("email") or user.get("sub") or "admin")
    row = await upsert_reporting_profile(
        pg,
        template_pack=pack,
        institution_display_name=inst,
        reporting_entity_name=rent,
        entity_registration_ref=reg,
        default_outputs=body.default_outputs or {},
        narrative_style=body.narrative_style.strip().lower(),
        updated_by=actor,
    )
    audit_trail.record_event_from_user(
        user,
        action="admin.reporting_profile_updated",
        resource_type="institution_reporting_profile",
        resource_id="1",
        details={"template_pack": pack},
    )
    return {"status": "ok", "profile": row, "default_outputs_effective": effective_default_outputs(row.get("default_outputs"))}


@router.get("/calendar")
async def get_report_calendar(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    pg = request.app.state.pg
    await ensure_reporting_profile_schema(pg)
    items = await list_calendar_entries(pg)
    return {"items": items, "upcoming_preview": upcoming_calendar_preview(items)}


class CalendarEntryCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=128)
    title: str = Field(..., min_length=2, max_length=500)
    report_family: str = Field(..., max_length=64)
    frequency: str = Field(..., description="daily | weekly | monthly | quarterly | annual | cron")
    cron_expression: Optional[str] = None
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    submission_offset_days: int = 0
    reminder_days_before: int = 1
    enabled: bool = True
    preferred_formats: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


@router.post("/calendar")
async def create_calendar_entry(
    request: Request,
    body: CalendarEntryCreate,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    if body.frequency.strip().lower() not in VALID_FREQUENCIES:
        raise HTTPException(status_code=400, detail="invalid frequency")
    pg = request.app.state.pg
    await ensure_reporting_profile_schema(pg)
    actor = str(user.get("email") or user.get("sub") or "admin")
    try:
        row = await insert_calendar_entry(
            pg,
            slug=body.slug,
            title=body.title,
            report_family=body.report_family,
            frequency=body.frequency,
            cron_expression=body.cron_expression,
            day_of_month=body.day_of_month,
            day_of_week=body.day_of_week,
            submission_offset_days=body.submission_offset_days,
            reminder_days_before=body.reminder_days_before,
            enabled=body.enabled,
            preferred_formats=body.preferred_formats or {},
            notes=body.notes,
            updated_by=actor,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="slug already exists") from e
        raise HTTPException(status_code=400, detail=str(e)) from e
    audit_trail.record_event_from_user(
        user,
        action="admin.reporting_calendar_created",
        resource_type="regulatory_report_calendar",
        resource_id=str(row.get("id") or ""),
        details={"slug": body.slug},
    )
    return {"status": "ok", "entry": row}


class CalendarEntryPatch(BaseModel):
    title: Optional[str] = None
    report_family: Optional[str] = None
    frequency: Optional[str] = None
    cron_expression: Optional[str] = None
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    submission_offset_days: Optional[int] = None
    reminder_days_before: Optional[int] = None
    enabled: Optional[bool] = None
    preferred_formats: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


@router.patch("/calendar/{entry_id}")
async def patch_calendar_entry(
    request: Request,
    entry_id: str,
    body: CalendarEntryPatch,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    pg = request.app.state.pg
    await ensure_reporting_profile_schema(pg)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "frequency" in fields:
        fields["frequency"] = str(fields["frequency"]).strip().lower()
    if "frequency" in fields and fields["frequency"] not in VALID_FREQUENCIES:
        raise HTTPException(status_code=400, detail="invalid frequency")
    actor = str(user.get("email") or user.get("sub") or "admin")
    row = await update_calendar_entry(pg, entry_id, fields, actor)
    if not row:
        raise HTTPException(status_code=404, detail="entry_not_found")
    audit_trail.record_event_from_user(
        user,
        action="admin.reporting_calendar_updated",
        resource_type="regulatory_report_calendar",
        resource_id=entry_id,
        details={"fields": list(fields.keys())},
    )
    return {"status": "ok", "entry": row}


@router.delete("/calendar/{entry_id}")
async def remove_calendar_entry(
    request: Request,
    entry_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    pg = request.app.state.pg
    await ensure_reporting_profile_schema(pg)
    ok = await delete_calendar_entry(pg, entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="entry_not_found")
    audit_trail.record_event_from_user(
        user,
        action="admin.reporting_calendar_deleted",
        resource_type="regulatory_report_calendar",
        resource_id=entry_id,
        details={},
    )
    return {"status": "ok"}
