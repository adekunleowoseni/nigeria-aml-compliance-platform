"""Admin CRUD for configurable AML red-flag rules + JSON bulk upload."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.security import get_current_user, require_admin
from app.services import red_flag_rules_db as rfdb
from app.services.red_flag_rules_service import invalidate_rules_cache

router = APIRouter(prefix="/admin/red-flags", tags=["admin", "red-flags"])


class RedFlagRuleBody(BaseModel):
    rule_code: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1, max_length=8000)
    enabled: bool = True
    match_patterns: List[str] = Field(default_factory=list)


@router.get("/rules")
async def list_red_flag_rules(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    pg = request.app.state.pg
    await rfdb.ensure_red_flag_rules_schema(pg)
    return {"items": await rfdb.list_rules(pg)}


@router.post("/rules")
async def create_or_update_rule(
    request: Request,
    body: RedFlagRuleBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    pg = request.app.state.pg
    await rfdb.ensure_red_flag_rules_schema(pg)
    actor = str(user.get("email") or user.get("sub") or "admin")
    try:
        row = await rfdb.upsert_rule(
            pg,
            rule_code=body.rule_code,
            title=body.title,
            description=body.description,
            enabled=body.enabled,
            match_patterns=body.match_patterns,
            updated_by=actor,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    invalidate_rules_cache()
    return {"status": "ok", "rule": row}


@router.delete("/rules/{rule_code}")
async def delete_red_flag_rule(
    request: Request,
    rule_code: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    pg = request.app.state.pg
    await rfdb.ensure_red_flag_rules_schema(pg)
    try:
        deleted = await rfdb.delete_rule(pg, rule_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    invalidate_rules_cache()
    return {"status": "ok", "deleted": rule_code}


@router.post("/upload-json")
async def upload_red_flags_json(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    body: Union[List[Dict[str, Any]], Dict[str, Any]] = Body(...),
):
    """
    Bulk upsert rules. Send a **JSON array** of rule objects, or an object with a
    **``rules``** or **``items``** array.

    Each object should include:
    ``rule_code``, ``title``, ``description``, optional ``match_patterns`` / ``keywords``,
    optional ``enabled``.

    Patterns are OR-matched (case-insensitive substring) against transaction narrative,
    remarks, KYC remarks, line of business, counterparty fields, and metadata JSON.
    Use ``regex:`` prefix for a regular expression (e.g. ``regex:\\bwire\\s+transfer\\b``).
    """
    require_admin(user)
    if isinstance(body, dict):
        items = body.get("rules") or body.get("items")
        if not isinstance(items, list):
            raise HTTPException(
                status_code=400,
                detail="When using an object wrapper, include a 'rules' or 'items' array",
            )
    elif isinstance(body, list):
        items = body
    else:
        raise HTTPException(status_code=400, detail="Body must be a JSON array or object with rules/items")
    pg = request.app.state.pg
    await rfdb.ensure_red_flag_rules_schema(pg)
    actor = str(user.get("email") or user.get("sub") or "admin")
    result = await rfdb.bulk_upsert_from_json(pg, items, updated_by=actor)
    invalidate_rules_cache()
    return {"status": "ok", **result}
