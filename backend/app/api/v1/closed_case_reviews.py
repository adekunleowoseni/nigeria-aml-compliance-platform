"""
Periodic review of closed alerts (CBN 5.7.b.ii): sampling, assignment, findings, tuning aggregation.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.v1.alerts import _seed_if_empty
from app.api.v1.auth import list_assignable_case_review_analysts
from app.config import settings
from app.core.security import get_current_user, require_admin
from app.services import audit_trail
from app.services.aml_runtime_store import get_aml_runtime_store
from app.services.closed_case_review_service import (
    filter_candidates,
    pick_reviewer_email,
    previous_calendar_month,
    reopen_closed_alert,
    sample_alerts,
    typology_pattern_choices,
)
from app.services.closed_case_reviews_db import (
    aggregate_tuning_proposals,
    batch_exists,
    ensure_closed_case_reviews_schema,
    get_review,
    insert_batch,
    insert_review,
    list_completed_with_recommendations,
    list_reviews,
    update_review_findings,
)
from app.services.mail_notify import _smtp_configured, send_plain_email

router = APIRouter(prefix="/compliance/closed-case-reviews", tags=["compliance", "closed-case-reviews"])


def _require_co_cco_or_admin(user: Dict[str, Any]) -> None:
    r = (user.get("role") or "").lower()
    if r not in ("admin", "compliance_officer", "chief_compliance_officer"):
        raise HTTPException(status_code=403, detail="Compliance officer, CCO, or admin access required")


def _can_access_review(user: Dict[str, Any], reviewer_id: Optional[str]) -> bool:
    r = (user.get("role") or "").lower()
    if r in ("admin", "chief_compliance_officer"):
        return True
    email = (user.get("email") or user.get("sub") or "").strip().lower()
    return bool(email and reviewer_id and email == str(reviewer_id).strip().lower())


@router.get("/patterns")
async def list_pattern_choices(user: Dict[str, Any] = Depends(get_current_user)):
    _require_co_cco_or_admin(user)
    return {"items": typology_pattern_choices()}


class GenerateBody(BaseModel):
    review_period_start: date
    review_period_end: date
    sample_type: str = Field(default="RANDOM", description="RANDOM, HIGH_RISK, or ALL")
    force: bool = Field(default=False, description="Admin: regenerate even if batch row exists (does not delete existing reviews).")


@router.post("/generate")
async def generate_review_sample(request: Request, body: GenerateBody, user: Dict[str, Any] = Depends(get_current_user)):
    _require_co_cco_or_admin(user)
    if body.force:
        require_admin(user)
    st = body.sample_type.strip().upper()
    if st not in ("RANDOM", "HIGH_RISK", "ALL"):
        raise HTTPException(status_code=400, detail="sample_type must be RANDOM, HIGH_RISK, or ALL")
    if body.review_period_end < body.review_period_start:
        raise HTTPException(status_code=400, detail="review_period_end before start")

    pg = request.app.state.pg
    await ensure_closed_case_reviews_schema(pg)
    if not body.force and await batch_exists(pg, period_start=body.review_period_start, period_end=body.review_period_end, sample_type=st):
        return {
            "status": "skipped",
            "reason": "batch_already_exists_for_period",
            "review_period_start": body.review_period_start.isoformat(),
            "review_period_end": body.review_period_end.isoformat(),
            "sample_type": st,
        }

    _seed_if_empty()
    analysts = list_assignable_case_review_analysts()
    if not analysts:
        raise HTTPException(status_code=400, detail="no_compliance_analysts_in_user_directory")

    all_alerts = await get_aml_runtime_store().alerts_values()
    candidates = filter_candidates(all_alerts, body.review_period_start, body.review_period_end, st)
    picked = sample_alerts(candidates, st)
    created: List[Dict[str, Any]] = []
    for a in picked:
        reviewer = pick_reviewer_email(a, analysts)
        row = await insert_review(
            pg,
            alert_id=a.id,
            period_start=body.review_period_start,
            period_end=body.review_period_end,
            sample_type=st,
            reviewer_id=reviewer,
        )
        if row:
            created.append(row)
            audit_trail.record_event_from_user(
                user,
                action="compliance.closed_case_review.queued",
                resource_type="closed_case_review",
                resource_id=str(row.get("id")),
                details={"alert_id": a.id, "reviewer_id": reviewer, "sample_type": st},
            )

    batch_row = await insert_batch(
        pg,
        period_start=body.review_period_start,
        period_end=body.review_period_end,
        sample_type=st,
        reviews_created=len(created),
    )
    audit_trail.record_event_from_user(
        user,
        action="compliance.closed_case_review.batch_generated",
        resource_type="closed_case_review_batch",
        resource_id=str((batch_row or {}).get("id") or f"{body.review_period_start}:{st}"),
        details={
            "candidates": len(candidates),
            "sampled": len(picked),
            "inserted": len(created),
            "sample_type": st,
        },
    )
    return {
        "status": "ok",
        "review_period_start": body.review_period_start.isoformat(),
        "review_period_end": body.review_period_end.isoformat(),
        "sample_type": st,
        "candidates_in_period": len(candidates),
        "sampled": len(picked),
        "reviews_created": len(created),
        "reviews": created,
    }


@router.get("")
async def list_closed_case_reviews(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    status: Optional[str] = Query(None),
    reviewer_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    _require_co_cco_or_admin(user)
    r = (user.get("role") or "").lower()
    email = (user.get("email") or user.get("sub") or "").strip().lower()
    rev_filter = reviewer_id
    if r == "compliance_officer" and not rev_filter:
        rev_filter = email
    rows, total = await list_reviews(
        request.app.state.pg,
        status=status,
        reviewer_id=rev_filter,
        skip=skip,
        limit=limit,
    )
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        aid = str(row.get("alert_id") or "")
        alert = await get_aml_runtime_store().alert_get(aid)
        enriched.append(
            {
                **row,
                "alert": alert.model_dump(mode="json") if alert else None,
            }
        )
    return {"items": enriched, "total": total, "skip": skip, "limit": limit}


class PutReviewBody(BaseModel):
    findings: str = Field(..., min_length=10, max_length=32000)
    pattern_identified: Optional[str] = Field(None, max_length=255)
    recommendation_tuning: Optional[str] = Field(None, max_length=8000)
    requires_reopen: bool = False
    notify_cco: bool = Field(
        default=False,
        description="Send CCO email when SMTP configured (also implied when requires_reopen is true).",
    )


@router.put("/{review_id}")
async def submit_review_findings(
    request: Request,
    review_id: str,
    body: PutReviewBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_co_cco_or_admin(user)
    pg = request.app.state.pg
    row = await get_review(pg, review_id)
    if not row:
        raise HTTPException(status_code=404, detail="review_not_found")
    if (row.get("review_status") or "").upper() == "COMPLETED":
        raise HTTPException(status_code=400, detail="review_already_completed")

    if not _can_access_review(user, row.get("reviewer_id")):
        raise HTTPException(status_code=403, detail="assigned_reviewer_only")

    _seed_if_empty()
    alert = await get_aml_runtime_store().alert_get(str(row.get("alert_id") or ""))
    reopened_id: Optional[str] = None
    if body.requires_reopen:
        if not alert:
            raise HTTPException(status_code=400, detail="original_alert_missing_cannot_reopen")
        reopened_id = await reopen_closed_alert(alert, review_id)

    updated = await update_review_findings(
        pg,
        review_id,
        findings=body.findings.strip(),
        pattern_identified=(body.pattern_identified or "").strip() or None,
        recommendation_tuning=(body.recommendation_tuning or "").strip() or None,
        requires_reopen=body.requires_reopen,
        reopened_alert_id=reopened_id,
        review_status="COMPLETED",
    )
    if not updated:
        raise HTTPException(status_code=400, detail="update_failed")

    audit_trail.record_event_from_user(
        user,
        action="compliance.closed_case_review.completed",
        resource_type="closed_case_review",
        resource_id=review_id,
        details={
            "alert_id": row.get("alert_id"),
            "pattern_identified": updated.get("pattern_identified"),
            "requires_reopen": body.requires_reopen,
            "reopened_alert_id": reopened_id,
        },
    )

    material = body.requires_reopen or body.notify_cco or len(body.findings) > 400
    if material:
        audit_trail.record_event_from_user(
            user,
            action="compliance.closed_case_review.material_finding",
            resource_type="closed_case_review",
            resource_id=review_id,
            details={"alert_id": row.get("alert_id"), "notify_cco_requested": body.notify_cco or body.requires_reopen},
        )

    cco = (settings.cco_email or "").strip()
    if cco and _smtp_configured() and (body.requires_reopen or body.notify_cco):
        try:
            sub = f"Closed case review — material finding — alert {row.get('alert_id')}"
            txt = (
                f"A periodic closed-case review was completed with findings that may require attention.\n\n"
                f"Review ID: {review_id}\n"
                f"Original alert: {row.get('alert_id')}\n"
                f"Reviewer: {row.get('reviewer_id')}\n"
                f"Requires re-open: {body.requires_reopen}\n"
                f"Re-opened alert ID: {reopened_id or '—'}\n"
                f"Pattern: {updated.get('pattern_identified') or '—'}\n\n"
                f"Findings:\n{body.findings[:8000]}\n"
            )
            await send_plain_email([cco], sub, txt)
        except Exception:
            pass

    return {"status": "ok", "review": updated, "reopened_alert_id": reopened_id}


@router.get("/tuning-proposals")
async def tuning_proposals(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=300),
):
    _require_co_cco_or_admin(user)
    agg = await aggregate_tuning_proposals(request.app.state.pg, limit=limit)
    recent = await list_completed_with_recommendations(request.app.state.pg, limit=min(limit, 50))
    return {"aggregated_by_pattern": agg, "recent_recommendations": recent}


async def run_monthly_closed_case_review_if_due(app: Any) -> Dict[str, Any]:
    """Call from background loop: on 1st UTC, generate previous month's sample if missing."""
    pg = getattr(getattr(app, "state", None), "pg", None)
    if pg is None:
        return {"ran": False, "reason": "no_pg"}
    await ensure_closed_case_reviews_schema(pg)
    today = datetime.now(timezone.utc).date()
    if today.day != 1:
        return {"ran": False, "reason": "not_first_of_month"}
    start, end = previous_calendar_month(today)
    if await batch_exists(pg, period_start=start, period_end=end, sample_type="RANDOM"):
        return {"ran": False, "reason": "batch_already_exists", "period": f"{start}..{end}"}

    _seed_if_empty()
    analysts = list_assignable_case_review_analysts()
    if not analysts:
        return {"ran": False, "reason": "no_analysts"}

    all_alerts = await get_aml_runtime_store().alerts_values()
    candidates = filter_candidates(all_alerts, start, end, "RANDOM")
    picked = sample_alerts(candidates, "RANDOM")
    created = 0
    for a in picked:
        reviewer = pick_reviewer_email(a, analysts)
        row = await insert_review(
            pg,
            alert_id=a.id,
            period_start=start,
            period_end=end,
            sample_type="RANDOM",
            reviewer_id=reviewer,
        )
        if row:
            created += 1
            audit_trail.record_event(
                action="compliance.closed_case_review.auto_queued",
                resource_type="closed_case_review",
                resource_id=str(row.get("id")),
                actor_sub="system",
                actor_email="system",
                actor_role="system",
                details={"alert_id": a.id, "reviewer_id": reviewer, "period": f"{start}..{end}"},
            )

    await insert_batch(
        pg,
        period_start=start,
        period_end=end,
        sample_type="RANDOM",
        reviews_created=created,
    )
    audit_trail.record_event(
        action="compliance.closed_case_review.monthly_batch",
        resource_type="closed_case_review_batch",
        resource_id=f"{start}:{end}:RANDOM",
        actor_sub="system",
        actor_email="system",
        actor_role="system",
        details={"reviews_created": created, "candidates": len(candidates), "sampled": len(picked)},
    )
    return {"ran": True, "reviews_created": created, "period_start": start.isoformat(), "period_end": end.isoformat()}
