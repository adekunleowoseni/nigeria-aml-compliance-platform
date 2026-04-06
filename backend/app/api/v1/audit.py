from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.core.security import get_current_user, require_cco_or_admin
from app.services import audit_trail

router = APIRouter(prefix="/audit")


def _viewer(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    require_cco_or_admin(user)
    return user


@router.get("/events")
async def list_audit_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    from_ts: Optional[str] = Query(None, description="ISO-8601 start (inclusive)"),
    to_ts: Optional[str] = Query(None, description="ISO-8601 end (inclusive)"),
    action_prefix: Optional[str] = None,
    action_contains: Optional[str] = None,
    resource_type: Optional[str] = None,
    actor_email: Optional[str] = None,
    q: Optional[str] = Query(None, description="Full-text search over JSON event"),
    user: Dict[str, Any] = Depends(_viewer),
):
    """Immutable audit trail: user actions, reports, auth, alert dispositions (paginated)."""
    items, total = audit_trail.query_events(
        skip=skip,
        limit=limit,
        from_ts=from_ts,
        to_ts=to_ts,
        action_prefix=action_prefix,
        action_contains=action_contains,
        resource_type=resource_type,
        actor_email=actor_email,
        q=q,
        report_only=False,
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/reports")
async def list_report_audit_entries(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    report_type: Optional[str] = Query(None, description="Filter: str, sar, ctr, aop, nfiu_cir, estr"),
    actor_email: Optional[str] = None,
    q: Optional[str] = None,
    user: Dict[str, Any] = Depends(_viewer),
):
    """Regulatory report generation, submission, and regeneration (audit entries)."""
    rf = report_type.strip().lower() if report_type and report_type.strip() else None
    items, total = audit_trail.query_events(
        skip=skip,
        limit=limit,
        from_ts=from_ts,
        to_ts=to_ts,
        action_prefix="report.",
        actor_email=actor_email,
        q=q,
        report_only=True,
        report_family=rf,
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/summary")
async def governance_summary(
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    user: Dict[str, Any] = Depends(_viewer),
):
    """Aggregated counts for compliance / operational review (demo)."""
    return audit_trail.governance_summary(from_ts=from_ts, to_ts=to_ts)


@router.get("/integrity")
async def verify_integrity(user: Dict[str, Any] = Depends(_viewer)):
    """Chain verification status, first/last event, broken links (GET snapshot)."""
    v = audit_trail.verify_chain()
    return {
        "valid": v.get("valid"),
        "events_verified": v.get("events_verified"),
        "verify_truncated": v.get("verify_truncated"),
        "chain_head": v.get("chain_head"),
        "broken_links": v.get("broken_links") or [],
        "first_event": v.get("first_event"),
        "last_event": v.get("last_event"),
        "storage": v.get("storage"),
        "postgres_total_rows": v.get("postgres_total_rows"),
        "retention_config": audit_trail.get_storage_config(),
    }


class AuditVerifyBody(BaseModel):
    max_events: int = Field(default=2_000_000, ge=1, le=2_000_000)


@router.post("/verify")
async def verify_integrity_post(
    body: AuditVerifyBody | None = None,
    user: Dict[str, Any] = Depends(_viewer),
):
    """Full hash-chain verification: each row recomputed; prev links continuous (same as GET, optional cap)."""
    cap = body.max_events if body else 2_000_000
    v = audit_trail.verify_chain(max_events=cap)
    return {
        "valid": v.get("valid"),
        "events_verified": v.get("events_verified"),
        "verify_truncated": v.get("verify_truncated"),
        "chain_head": v.get("chain_head"),
        "broken_links": v.get("broken_links") or [],
        "first_event": v.get("first_event"),
        "last_event": v.get("last_event"),
        "storage": v.get("storage"),
        "postgres_total_rows": v.get("postgres_total_rows"),
    }


class InternalAuditEventBody(BaseModel):
    action: str
    resource_type: str
    resource_id: str
    actor_sub: str = "system"
    actor_email: str = ""
    actor_role: str = ""
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None


def _require_audit_internal_key(x_audit_internal_key: Optional[str] = Header(None)) -> None:
    expected = (settings.audit_internal_api_key or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="internal audit ingest is disabled (set AUDIT_INTERNAL_API_KEY)")
    if not x_audit_internal_key or x_audit_internal_key.strip() != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-Audit-Internal-Key")


@router.post("/event", dependencies=[Depends(_require_audit_internal_key)])
async def ingest_internal_audit_event(body: InternalAuditEventBody):
    """Append-only ingest for services; uses hash chain via audit_events_store when backend is postgres."""
    return audit_trail.record_event(
        action=body.action.strip(),
        resource_type=body.resource_type.strip(),
        resource_id=body.resource_id.strip(),
        actor_sub=body.actor_sub.strip() or "system",
        actor_email=(body.actor_email or "").strip(),
        actor_role=(body.actor_role or "").strip(),
        details=body.details,
        ip_address=body.ip_address,
    )


@router.get("/retention-config")
async def retention_config(user: Dict[str, Any] = Depends(_viewer)):
    """Effective storage backend and document retention settings (env-driven)."""
    return audit_trail.get_storage_config()


@router.get("/export")
async def export_audit(
    format: str = Query("csv", description="csv or json"),
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    user: Dict[str, Any] = Depends(_viewer),
):
    """Bulk export for Internal Audit / regulators (does not block other API traffic)."""
    fmt = format.lower().strip()
    audit_trail.record_event_from_user(
        user,
        action="audit.governance.export",
        resource_type="audit_trail",
        resource_id=f"export-{fmt}",
        details={"from_ts": from_ts, "to_ts": to_ts, "format": fmt},
    )
    if fmt == "json":
        body = audit_trail.export_events_json(from_ts=from_ts, to_ts=to_ts)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="audit_export.json"'},
        )
    if fmt == "csv":
        body = audit_trail.export_events_csv(from_ts=from_ts, to_ts=to_ts)
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="audit_export.csv"'},
        )
    raise HTTPException(status_code=400, detail="format must be csv or json")
