"""Admin upload of sanctions, PEP, and adverse-media reference lists (JSON or XML) + full-database screening."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.core.security import get_current_user, get_current_user_or_reference_internal, require_admin
from app.services import reference_lists_db as rldb
from app.services.reference_lists_service import (
    LIST_TYPES,
    get_counts,
    parse_upload,
    preview_list_items,
    replace_list,
    run_full_customer_screening_scan,
    screen_customer_name,
)

router = APIRouter(prefix="/admin/reference-lists", tags=["admin", "reference-lists"])


def _require_admin_or_scheduled(user: Dict[str, Any]) -> None:
    if user.get("sub") == "reference-lists-internal":
        return
    require_admin(user)


class ScreenNameBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    threshold: Optional[int] = Field(None, ge=50, le=100)


@router.get("")
async def reference_lists_summary(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    pg = request.app.state.pg
    latest = None
    try:
        latest = await rldb.fetch_latest_screening_run(pg)
    except Exception:
        latest = None
    return {"counts": get_counts(), "latest_screening_run": latest}


@router.post("/screening/run-now")
async def screening_run_now(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user_or_reference_internal),
):
    _require_admin_or_scheduled(user)
    pg = request.app.state.pg
    summary = await run_full_customer_screening_scan(pg, persist=True)
    return {"status": "ok", **summary}


@router.get("/screening/latest")
async def screening_latest(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    pg = request.app.state.pg
    row = await rldb.fetch_latest_screening_run(pg)
    if not row:
        return {"latest": None}
    return {"latest": dict(row)}


@router.post("/screening/try-name")
async def screening_try_name(request: Request, body: ScreenNameBody, user: Dict[str, Any] = Depends(get_current_user)):
    """Admin-only: fuzzy-match a single name against in-memory lists (tiling aid)."""
    require_admin(user)
    return screen_customer_name(body.name, body.threshold)


@router.get("/{list_type}/preview")
async def preview_list(
    request: Request,
    list_type: str,
    user: Dict[str, Any] = Depends(get_current_user),
    limit: int = 20,
):
    require_admin(user)
    if list_type not in LIST_TYPES:
        raise HTTPException(status_code=400, detail="Invalid list_type")
    lim = max(1, min(200, limit))
    try:
        total, items = preview_list_items(list_type, lim)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid list_type") from None
    return {"list_type": list_type, "total": total, "items": items}


@router.post("/{list_type}/upload")
async def upload_reference_list(
    request: Request,
    list_type: str,
    user: Dict[str, Any] = Depends(get_current_user),
    file: Optional[UploadFile] = File(None),
):
    require_admin(user)
    if list_type not in LIST_TYPES:
        raise HTTPException(status_code=400, detail="Invalid list_type")
    actor = str(user.get("email") or user.get("sub") or "admin")
    pg = request.app.state.pg

    if file is not None and (file.filename or "").strip():
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Empty file")
        try:
            items = parse_upload(raw, content_type=file.content_type, filename=file.filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail="Send a JSON/XML body or multipart file")
        try:
            items = parse_upload(body, content_type=request.headers.get("content-type"), filename=None)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    await replace_list(pg, list_type, items, actor)
    return {"status": "ok", "list_type": list_type, "records_loaded": len(items)}
