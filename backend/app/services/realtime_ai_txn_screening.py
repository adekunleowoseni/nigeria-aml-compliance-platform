"""LLM pass on individual transactions for narrative clarity, destination/purpose risk, and EDD prompts."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from app.config import settings
from app.core.logging import get_logger
from app.services.llm.client import get_llm_client
from app.services.typology_rules import TypologyHit

log = get_logger(component="realtime_ai_txn_screening")


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


async def run_realtime_ai_transaction_screening(
    txn: Dict[str, Any],
    *,
    kyc_context: Dict[str, Any],
    baseline_inflow_count: int,
    ytd_inflow_total: float,
    existing_rule_ids: Sequence[str],
) -> List[TypologyHit]:
    """
    When enabled, asks the configured LLM to flag confusing narrations / suspicious purpose-destination mixes.
    Returns additional TypologyHit rows (may be empty).
    """
    if not settings.aml_realtime_llm_screening:
        return []
    narrative = f"{txn.get('narrative') or ''} {txn.get('remarks') or ''}".strip()
    if len(narrative) < 12:
        return []

    system = (
        "You are a Nigerian bank AML analyst assistant. Reply with ONLY a compact JSON object, no markdown. "
        "Schema: {\"suspicious\": boolean, \"request_edd\": boolean, \"summary\": string under 400 chars, "
        "\"factors\": string[] max 5 items}. "
        "Assess the live transaction against KYC: occupation, declared annual turnover, and officer remarks. "
        "Flag confusing mixes of purpose vs destination (e.g. government or corporate sender to personal account "
        "without clear salary/dividend/contract support), vague narrations, sanctions- or PEP-style hints, "
        "structuring language, or economic implausibility vs expected turnover. "
        "request_edd=true when purpose, destination, beneficiary, or narration needs customer clarification. "
        "suspicious=true when ML/FT risk is plausible even if deterministic rules already fired."
    )
    prompt = (
        f"Customer segment: {kyc_context.get('customer_segment')}\n"
        f"Declared expected annual turnover (if any): {kyc_context.get('expected_annual_turnover')}\n"
        f"Line of business: {kyc_context.get('line_of_business')}\n"
        f"Officer/customer remarks on file: {kyc_context.get('customer_remarks') or '(none)'}\n"
        f"YTD inbound total (same calendar year, heuristic): ₦{ytd_inflow_total:,.0f}\n"
        f"Prior inbound txn count (baseline): {baseline_inflow_count}\n"
        f"Rules already triggered by engine: {', '.join(existing_rule_ids) or '(none)'}\n\n"
        f"Transaction JSON:\n{json.dumps(txn, default=str)[:8000]}\n"
    )
    try:
        client = get_llm_client()
        result = await client.generate(prompt, system=system, temperature=0.15)
        data = _extract_json_object(result.content)
        if not isinstance(data, dict):
            return []
        suspicious = bool(data.get("suspicious"))
        request_edd = bool(data.get("request_edd"))
        summary = str(data.get("summary") or "").strip()
        factors = data.get("factors")
        factor_txt = ""
        if isinstance(factors, list):
            factor_txt = "; ".join(str(x) for x in factors[:5] if str(x).strip())
        hits: List[TypologyHit] = []
        if request_edd:
            nar = (summary or "Model suggests clarification.") + (f" Factors: {factor_txt}" if factor_txt else "")
            hits.append(
                TypologyHit(
                    rule_id="TYP-AI-EDD",
                    title="AI review: enhanced due diligence / clarification",
                    narrative=nar[:900],
                    nfiu_reference="EDD / customer clarification",
                )
            )
        elif suspicious and summary:
            hits.append(
                TypologyHit(
                    rule_id="TYP-AI-SUSPICIOUS-NARRATIVE",
                    title="AI review: suspicious purpose or destination hints",
                    narrative=(summary + (f" ({factor_txt})" if factor_txt else ""))[:900],
                    nfiu_reference="Unusual transaction purpose",
                )
            )
        return hits
    except Exception:
        log.exception("realtime_ai_txn_screening_failed")
        return []
