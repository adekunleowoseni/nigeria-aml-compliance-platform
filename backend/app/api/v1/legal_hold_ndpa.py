"""Legal hold placement and NDPA-style data subject access (retention window / soft-deleted snapshots)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.v1.in_memory_stores import _ALERTS, _TXNS
from app.core.security import get_current_user
from app.services.retention_policies_db import (
    delete_legal_hold,
    ensure_retention_schema,
    insert_legal_hold,
    list_legal_holds,
    ndpa_fetch_kyc_including_deleted,
    ndpa_registry_snapshots_for_customer,
)

router = APIRouter(prefix="/compliance", tags=["compliance", "legal-hold", "ndpa"])


def _require_co_cco_admin(user: Dict[str, Any]) -> None:
    r = (user.get("role") or "").lower()
    if r not in ("admin", "compliance_officer", "chief_compliance_officer"):
        raise HTTPException(status_code=403, detail="Compliance officer, CCO, or admin required")


class LegalHoldBody(BaseModel):
    record_type: str = Field(..., max_length=50)
    record_id: str = Field(..., max_length=255)
    hold_reason: Optional[str] = Field(None, max_length=4000)
    expires_at: Optional[datetime] = None


@router.post("/legal-hold")
async def create_legal_hold(
    request: Request,
    body: LegalHoldBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_co_cco_admin(user)
    pg = request.app.state.pg
    await ensure_retention_schema(pg)
    placed_by = str(user.get("email") or user.get("sub") or "unknown")
    row = await insert_legal_hold(
        pg,
        record_type=body.record_type,
        record_id=body.record_id,
        hold_reason=body.hold_reason,
        placed_by=placed_by,
        expires_at=body.expires_at,
    )
    return {"status": "ok", "hold": row}


@router.delete("/legal-hold/{hold_id}")
async def remove_legal_hold(
    request: Request,
    hold_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_co_cco_admin(user)
    pg = request.app.state.pg
    ok = await delete_legal_hold(pg, hold_id)
    if not ok:
        raise HTTPException(status_code=404, detail="hold_not_found")
    return {"status": "ok"}


@router.get("/legal-holds")
async def list_holds(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=300),
):
    _require_co_cco_admin(user)
    pg = request.app.state.pg
    await ensure_retention_schema(pg)
    return {"items": await list_legal_holds(pg, limit=limit)}


@router.get("/data-subject-access")
async def data_subject_access(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    customer_id: str = Query(..., min_length=1, max_length=256),
):
    """
    NDPA-oriented package: active + soft-deleted KYC row, related in-memory alerts/transactions (including soft-deleted),
    and registry snapshots mentioning the customer (within retention / before hard purge).
    """
    _require_co_cco_admin(user)
    pg = request.app.state.pg
    await ensure_retention_schema(pg)
    cid = customer_id.strip()

    kyc_rows = await ndpa_fetch_kyc_including_deleted(pg, cid)
    registry_hits = await ndpa_registry_snapshots_for_customer(pg, cid)

    alerts_out: List[Dict[str, Any]] = []
    for a in _ALERTS.values():
        if (a.customer_id or "").strip() == cid:
            alerts_out.append(a.model_dump(mode="json"))

    tx_out: List[Dict[str, Any]] = []
    for t in _TXNS.values():
        if (t.customer_id or "").strip() == cid:
            tx_out.append(t.model_dump(mode="json"))

    return {
        "customer_id": cid,
        "kyc_records": kyc_rows,
        "alerts": alerts_out,
        "transactions": tx_out,
        "retention_registry_snapshots": registry_hits,
        "note": "Includes soft-deleted entities still in memory or registry; hard-purged data is not recoverable.",
    }
