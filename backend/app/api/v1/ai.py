from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.core.security import get_current_user
from app.services import audit_trail
from app.services.llm.client import get_llm_client

router = APIRouter(prefix="/ai")


class LlmSettingsBody(BaseModel):
    provider: Literal["gemini", "openai", "ollama"] = Field(..., description="Selected AI provider")


class RefineReportBody(BaseModel):
    draft_text: str = Field(..., min_length=1, description="Draft narrative text to refine.")
    instruction: Optional[str] = Field(
        default=None,
        description="Optional instruction for style/tone/output constraints.",
    )
    alert_id: Optional[str] = None


def _require_admin(user: Dict[str, Any]) -> None:
    if (user.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/settings")
async def get_ai_settings(user: Dict[str, Any] = Depends(get_current_user)):
    _require_admin(user)
    return {
        "provider": (settings.llm_provider or "gemini").lower(),
        "available_providers": ["gemini", "openai", "ollama"],
        "defaults": {
            "gemini_model": settings.gemini_model,
            "openai_model": settings.openai_model,
            "ollama_model": settings.ollama_model,
        },
    }


@router.put("/settings")
async def update_ai_settings(
    body: LlmSettingsBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(user)
    prev = (settings.llm_provider or "gemini").lower()
    settings.llm_provider = body.provider
    audit_trail.record_event_from_user(
        user,
        action="admin.ai_settings.updated",
        resource_type="configuration",
        resource_id="llm_provider",
        details={"previous": prev, "current": (settings.llm_provider or "").lower()},
    )
    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "message": f"AI provider switched to {settings.llm_provider}.",
    }


@router.post("/decision-support")
async def decision_support(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Provider-agnostic LLM endpoint.
    Input:
      - transaction: dict
      - customer_profile: dict (optional)
      - remarks: str (optional)
      - prompt_override: str (optional)
    """
    txn = payload.get("transaction")
    if not isinstance(txn, dict):
        raise HTTPException(status_code=400, detail="transaction (object) is required")
    profile: Optional[Dict[str, Any]] = payload.get("customer_profile") if isinstance(payload.get("customer_profile"), dict) else None
    remarks = payload.get("remarks") or txn.get("narrative") or ""

    prompt_override = payload.get("prompt_override")
    if prompt_override:
        prompt = str(prompt_override)
    else:
        prompt = (
            "You are an AML decision-support assistant. Read the customer profile and transaction remarks, then:\n"
            "1) classify likely typology (smurfing/fan-in, layering, structuring, mule activity, profile mismatch)\n"
            "2) explain in 5-8 bullet points\n"
            "3) recommend next action (monitor / STR draft / freeze / request KYC)\n\n"
            f"Customer profile: {profile}\n"
            f"Transaction: {txn}\n"
            f"Remarks: {remarks}\n"
        )

    llm = get_llm_client()
    result = await llm.generate(prompt)
    return {"provider": result.provider, "model": result.model, "summary": result.content, "raw": result.raw}


@router.post("/refine-report")
async def refine_report(
    body: RefineReportBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    instruction = (body.instruction or "").strip() or (
        "Refine this STR report narrative for clarity, regulatory tone, and readability. "
        "Keep all factual details accurate and do not invent any data."
    )
    prompt = (
        "You are an AML compliance reporting assistant.\n\n"
        "Task:\n"
        f"{instruction}\n\n"
        "Rules:\n"
        "- Keep all facts, names, dates, amounts, and identifiers unchanged unless grammar fixes are required.\n"
        "- Do not invent details.\n"
        "- Return only the refined report text (no headings, no explanations).\n\n"
        "Draft text:\n"
        f"{body.draft_text.strip()}\n"
    )
    llm = get_llm_client()
    result = await llm.generate(prompt)
    out = (result.content or "").strip()
    if not out:
        raise HTTPException(status_code=502, detail="AI returned an empty response for report refinement.")
    audit_trail.record_event_from_user(
        user,
        action="ai.refine_report",
        resource_type="alert" if body.alert_id else "document",
        resource_id=(body.alert_id or "str_draft"),
        details={"provider": result.provider, "model": result.model, "input_chars": len(body.draft_text)},
    )
    return {"provider": result.provider, "model": result.model, "refined_text": out}

