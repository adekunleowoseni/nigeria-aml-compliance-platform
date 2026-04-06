"""Admin retention policy configuration and manual job trigger (CBN 5.11.b.ii)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.core.security import get_current_user, get_current_user_or_retention_internal, require_admin
from app.services.retention_policies_db import ensure_retention_schema, list_policies, upsert_policy
from app.services.retention_runner import run_retention_job

router = APIRouter(prefix="/admin/retention", tags=["admin", "retention"])


def _admin_or_internal_key(
    user: Dict[str, Any],
    x_retention_internal_key: Optional[str] = Header(None, alias="X-Retention-Internal-Key"),
) -> str:
    key = (settings.retention_internal_api_key or "").strip()
    if key and (x_retention_internal_key or "").strip() == key:
        return "celery@internal"
    require_admin(user)
    return str(user.get("email") or user.get("sub") or "admin")


@router.get("/policies")
async def get_policies(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    pg = request.app.state.pg
    await ensure_retention_schema(pg)
    return {"items": await list_policies(pg)}


class PolicyRow(BaseModel):
    record_type: str = Field(..., max_length=50)
    retention_days: int = Field(..., ge=1, le=36500)
    action: str = Field(default="DELETE")
    is_active: bool = True


class PutPoliciesBody(BaseModel):
    policies: List[PolicyRow]


@router.put("/policies")
async def put_policies(request: Request, body: PutPoliciesBody, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    pg = request.app.state.pg
    await ensure_retention_schema(pg)
    actor = str(user.get("email") or user.get("sub") or "admin")
    out: List[Dict[str, Any]] = []
    for p in body.policies:
        act = (p.action or "DELETE").strip().upper()
        if act not in ("DELETE", "ARCHIVE", "ANONYMIZE"):
            raise HTTPException(status_code=400, detail=f"invalid action for {p.record_type}")
        row = await upsert_policy(
            pg,
            record_type=p.record_type,
            retention_days=p.retention_days,
            action=act,
            is_active=p.is_active,
            updated_by=actor,
        )
        out.append(row)
    return {"status": "ok", "policies": out}


@router.post("/run-now")
async def run_retention_now(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user_or_retention_internal),
    x_retention_internal_key: Optional[str] = Header(None, alias="X-Retention-Internal-Key"),
):
    """
    Execute retention pass in this API process (required for in-memory alerts/transactions/reports).
    Celery Beat can call with ``X-Retention-Internal-Key`` matching ``RETENTION_INTERNAL_API_KEY``.
    """
    actor = _admin_or_internal_key(user, x_retention_internal_key)
    pg = request.app.state.pg
    await ensure_retention_schema(pg)
    stats = await run_retention_job(
        pg,
        include_memory=True,
        grace_hard_purge_days=max(1, int(settings.retention_hard_purge_grace_days)),
        actor_email=actor,
    )
    return {"status": "ok", "stats": stats}
