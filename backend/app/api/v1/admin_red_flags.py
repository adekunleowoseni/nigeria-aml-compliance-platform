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


def _typology_rule_catalog() -> List[Dict[str, Any]]:
    return [
        {"rule_id": "TYP-HUGE-INFLOW-THRESHOLD", "title": "Large inbound credit vs policy threshold", "description": "Flags NGN inflows above configured individual/corporate thresholds."},
        {"rule_id": "TYP-NEAR-POLICY-CEILING", "title": "Inbound clustered below policy threshold", "description": "Flags inflows close to threshold as potential avoidance/structuring."},
        {"rule_id": "TYP-YTD-EXCEEDS-DECLARED-TURNOVER", "title": "YTD inflows exceed declared turnover", "description": "Compares cumulative inflows to expected annual turnover from KYC."},
        {"rule_id": "TYP-FIRST-HUGE", "title": "Step-change amount vs history", "description": "Flags amounts materially above prior customer maxima."},
        {"rule_id": "TYP-FIRST-LARGE-INFLOW", "title": "First large inbound credit", "description": "Flags large inbound where prior inbound history is minimal."},
        {"rule_id": "TYP-PATTERN-INCONSISTENT", "title": "Inbound pattern inconsistent", "description": "Statistical deviation from recent inbound distribution."},
        {"rule_id": "TYP-SUDDEN-MOVEMENT", "title": "Sudden movement / velocity cluster", "description": "Flags compressed high-volume activity in short windows."},
        {"rule_id": "TYP-RAPID-INFLOW-OUTFLOW", "title": "Rapid inbound then outbound movement", "description": "Pass-through/layering indicator based on substantial in-out cycles."},
        {"rule_id": "TYP-DORMANT-REACTIVATION", "title": "Dormant account reactivation", "description": "Large inbound after prolonged inactivity."},
        {"rule_id": "TYP-FAN-IN", "title": "Multiple inbound sources", "description": "Consolidation pattern from many counterparties to one account."},
        {"rule_id": "TYP-FAN-OUT", "title": "Multiple outbound destinations", "description": "Distribution/layering pattern to many beneficiaries."},
        {"rule_id": "TYP-STRUCTURING", "title": "Structured/split inflows", "description": "Heuristic detection of several similarly-sized small inflows."},
        {"rule_id": "TYP-CORP-TO-INDIVIDUAL", "title": "Corporate-to-individual flow", "description": "Corporate counterparty crediting individual relationship."},
        {"rule_id": "TYP-GOV-FLOW", "title": "Government-themed flow references", "description": "Narrative/counterparty includes public-sector/ministry context."},
        {"rule_id": "TYP-PROFILE-MISMATCH", "title": "Occupation/profile mismatch", "description": "Narrative inconsistent with declared customer profile/occupation."},
        {"rule_id": "TYP-EXPECTED-TURNOVER", "title": "Amount vs declared expectation", "description": "Single transaction far above expected turnover guidance."},
        {"rule_id": "TYP-CRYPTO-KEYWORD", "title": "Crypto/virtual asset wording", "description": "Detects crypto-related terms in narration/remarks."},
        {"rule_id": "TYP-INDIV-PAYROLL", "title": "Payroll-like activity on individual account", "description": "Individual account used like payroll/business payout channel."},
        {"rule_id": "TYP-CHANNEL-HOP", "title": "Channel hopping across products", "description": "Wallet/investment/savings movement indicating possible layering."},
        {"rule_id": "TYP-TRADE-PRICING", "title": "Trade pricing anomaly wording", "description": "Narrative hints at non-market pricing/invoice inflation."},
        {"rule_id": "TYP-SENSITIVE-GOODS", "title": "Sensitive goods reference", "description": "Mentions controlled/sensitive goods categories."},
        {"rule_id": "TYP-TRAFFICKING-KEYWORD", "title": "Trafficking/high-risk human-security wording", "description": "Mentions trafficking/organ-harvest/related indicators."},
        {"rule_id": "TYP-PEP", "title": "PEP exposure indicator", "description": "Text/metadata indicates politically exposed person risk."},
        {"rule_id": "TYP-SANCTIONS-JURISDICTION", "title": "High-risk jurisdiction reference", "description": "Mentions sanctioned/high-risk jurisdictions for enhanced checks."},
    ]


def _anomaly_rule_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "rule_id": "ANOM-IFOREST-CORE",
            "title": "Isolation Forest anomaly scoring",
            "description": "Scores amount/currency/type/hour feature vector and flags when score >= anomaly threshold.",
            "parameters": {
                "model": "IsolationForest(n_estimators=200, contamination=0.02, random_state=42)",
                "fit_min_baseline": 50,
                "features": ["amount", "is_ngn", "is_wire", "is_cash", "hour_of_day"],
            },
        },
        {
            "rule_id": "ANOM-BULK-REFIT",
            "title": "Bulk simulation periodic refit",
            "description": "During temporal/bulk simulation, per-customer model refits every N baseline rows.",
            "parameters": {"default_refit_every": 500},
        },
    ]


@router.get("/rule-catalog")
async def detection_rule_catalog(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    pg = request.app.state.pg
    await rfdb.ensure_red_flag_rules_schema(pg)
    red_flags = await rfdb.list_rules(pg)
    return {
        "red_flag_rules": red_flags,
        "typology_rules": _typology_rule_catalog(),
        "anomaly_rules": _anomaly_rule_catalog(),
        "pattern_sources": [
            {
                "source": "Custom red-flag match_patterns",
                "description": "Admin-managed keywords/regex applied to narrative, remarks, KYC remarks, counterparty fields, transaction type, channel, and metadata JSON.",
            },
            {
                "source": "Typology keyword detectors",
                "description": "Built-in keyword/regex families: crypto, government/public-sector, PEP, sanctions jurisdictions, trafficking/sensitive goods, and profile mismatch lexicons.",
            },
        ],
    }


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
