"""Optional LLM narratives for AOP / NFIU CIR Word exports (compliance bundle)."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from app.core.logging import get_logger

log = get_logger(component="compliance_bundle_narratives")

_AOP_SYSTEM = (
    "You are a Nigerian bank compliance officer drafting internal narrative text for an Account Opening Package (AOP) "
    "supporting document. Write 4–6 short paragraphs in formal English. No markdown. Reference the customer and product "
    "factually; label uncertain items as demo placeholders."
)

_CIR_SYSTEM = (
    "You are a Nigerian bank compliance officer drafting internal narrative text for an NFIU-style customer information "
    "change notification supporting document. Write 4–6 short paragraphs in formal English. No markdown. Describe the "
    "change type, old vs new values at a high level, and internal verification steps (demo)."
)


def _template_aop(customer_id: str, product: str, risk: str, customer_name: str) -> str:
    return (
        f"This Account Opening Package (AOP) summary relates to customer identifier {customer_id} ({customer_name}) "
        f"for product {product} with initial risk rating {risk}.\n\n"
        "The onboarding file was assembled from KYC records held on the demo platform, including identity verification "
        "and screening placeholders.\n\n"
        "No material exceptions were noted in the demo dataset beyond standard enhanced monitoring for higher-risk profiles.\n\n"
        "This narrative accompanies the goAML-style AOP XML extract for internal review and regulatory packaging (demo)."
    )


def _template_cir(
    change_type: str,
    customer_id: str,
    fields: Dict[str, Any],
) -> str:
    parts = [
        f"Customer information change type: {change_type}. Subject customer identifier: {customer_id}.",
        "The institution has recorded the following change request in the demo environment.",
    ]
    for k in ("name_old", "name_new", "bvn_old", "bvn_new", "dob_old", "dob_new", "notes"):
        v = fields.get(k)
        if v:
            parts.append(f"{k}: {v}")
    parts.append(
        "Internal compliance has reviewed supporting documentation on file (demo). "
        "This narrative supports the NFIU customer information change XML extract."
    )
    return "\n\n".join(parts)


async def build_aop_bundle_narrative(
    *,
    customer_id: str,
    customer_name: str,
    account_product: str,
    risk_rating: str,
    str_notes_summary: Optional[str],
    use_llm: bool,
) -> Tuple[str, str]:
    if not use_llm:
        return _template_aop(customer_id, account_product, risk_rating, customer_name), "template"
    ctx = {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "account_product": account_product,
        "risk_rating": risk_rating,
        "str_context": (str_notes_summary or "")[:2000],
    }
    prompt = f"Case context (JSON):\n{json.dumps(ctx, indent=2)}\n\nWrite the AOP internal narrative paragraphs."
    try:
        from app.services.llm.client import get_llm_client

        client = get_llm_client()
        res = await client.generate(prompt, system=_AOP_SYSTEM, temperature=0.35)
        text = (res.content or "").strip()
        if len(text) < 80:
            raise ValueError("llm_aop_too_short")
        return text[:12000], "llm"
    except Exception as exc:
        log.info("aop_bundle_narrative_llm_skipped err=%s", exc)
        return _template_aop(customer_id, account_product, risk_rating, customer_name), "template"


async def build_nfiu_cir_bundle_narrative(
    *,
    change_type: str,
    customer_id: str,
    fields: Dict[str, Any],
    use_llm: bool,
) -> Tuple[str, str]:
    if not use_llm:
        return _template_cir(change_type, customer_id, fields), "template"
    ctx = {"change_type": change_type, "customer_id": customer_id, **{k: fields.get(k) for k in fields}}
    prompt = f"Change case (JSON):\n{json.dumps(ctx, default=str, indent=2)[:8000]}\n\nWrite the CIR internal narrative."
    try:
        from app.services.llm.client import get_llm_client

        client = get_llm_client()
        res = await client.generate(prompt, system=_CIR_SYSTEM, temperature=0.35)
        text = (res.content or "").strip()
        if len(text) < 80:
            raise ValueError("llm_cir_too_short")
        return text[:12000], "llm"
    except Exception as exc:
        log.info("cir_bundle_narrative_llm_skipped err=%s", exc)
        return _template_cir(change_type, customer_id, fields), "template"
