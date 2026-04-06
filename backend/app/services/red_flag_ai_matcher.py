"""
LLM maps transaction remarks + customer activity to the institutional red-flag catalog.
Produces catalog rule hits and optional AI-only suspicions when no rule fits; optional DB log for review.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Set

from app.config import settings
from app.core.logging import get_logger
from app.db.postgres_client import PostgresClient
from app.services import red_flag_rules_db as rfdb
from app.services.llm.client import get_llm_client
from app.services.realtime_ai_txn_screening import _extract_json_object
from app.services.transaction_analytics import _is_inflow, _is_outflow, _txn_ts
from app.services.typology_rules import TypologyHit

log = get_logger(component="red_flag_ai_matcher")


def build_customer_activity_summary(
    customer_id: str,
    baseline_txns: Sequence[Dict[str, Any]],
    current_txn: Dict[str, Any],
    *,
    window_days: int = 90,
) -> str:
    """Compact behavioural summary from prior transactions (same customer)."""
    cid = str(customer_id)
    ts0 = _txn_ts(current_txn)
    start = ts0 - timedelta(days=window_days)
    rows = [
        t
        for t in baseline_txns
        if str(t.get("customer_id") or "") == cid and _txn_ts(t) < ts0 and _txn_ts(t) >= start
    ]
    in_amt = sum(float(t.get("amount") or 0) for t in rows if _is_inflow(t))
    out_amt = sum(float(t.get("amount") or 0) for t in rows if _is_outflow(t))
    in_n = sum(1 for t in rows if _is_inflow(t))
    out_n = sum(1 for t in rows if _is_outflow(t))
    cps: Set[str] = set()
    for t in rows:
        md = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        cp = str(t.get("counterparty_id") or md.get("counterparty_id") or "").strip()
        if cp:
            cps.add(cp)
    amts = [float(t.get("amount") or 0) for t in rows]
    max_prior = max(amts) if amts else 0.0
    last_ts = max((_txn_ts(t) for t in rows), default=None)
    gap_days = ""
    if last_ts is not None:
        gap_days = str(max(0, (ts0 - last_ts).days))

    return (
        f"Prior {window_days}d (excluding current txn): count={len(rows)}, "
        f"inflows={in_n} total ≈₦{in_amt:,.0f}, outflows={out_n} total ≈₦{out_amt:,.0f}, "
        f"distinct prior counterparties≈{len(cps)}, max single prior amount≈₦{max_prior:,.0f}, "
        f"days since last prior txn={gap_days or 'n/a'}."
    )


def _norm_catalog_code(code: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "", (code or "").strip().lower())[:128]


async def run_red_flag_llm_matcher(
    pg: Optional[PostgresClient],
    txn: Dict[str, Any],
    baseline_txns: Sequence[Dict[str, Any]],
    *,
    customer_id: str,
    customer_remarks: str = "",
    line_of_business: str = "",
    kyc_segment: str = "",
    expected_annual_turnover: Optional[float] = None,
    customer_name: str = "",
    pattern_matched_rule_codes: Optional[List[str]] = None,
    transaction_id: Optional[str] = None,
) -> List[TypologyHit]:
    """
    Ask the LLM to select catalog ``rule_code`` values and/or AI-only suspicions
    using narration, remarks, metadata, and customer activity summary.
    """
    if not settings.aml_red_flag_llm_matching or pg is None:
        return []

    try:
        all_rows = await rfdb.list_rules(pg, enabled_only=True)
    except Exception:
        log.exception("red_flag_llm_catalog_load_failed")
        return []

    max_n = max(5, min(200, int(settings.aml_red_flag_llm_max_catalog_rules)))
    rows = sorted(all_rows, key=lambda r: str(r.get("rule_code") or ""))[:max_n]
    if not rows:
        return []

    code_to_row = {str(r.get("rule_code") or "").strip().lower(): r for r in rows}
    catalog_lines: List[str] = []
    for r in rows:
        rc = str(r.get("rule_code") or "").strip()
        tit = str(r.get("title") or rc)
        desc = str(r.get("description") or "")[:420].replace("\n", " ")
        catalog_lines.append(f"- {rc}: {tit} — {desc}")

    catalog_text = "\n".join(catalog_lines)
    activity = build_customer_activity_summary(customer_id, baseline_txns, txn)
    pat = pattern_matched_rule_codes or []
    pat_txt = ", ".join(pat) if pat else "(none — no keyword red-flag match yet)"

    system = (
        "You are a senior AML analyst for a Nigerian financial institution. "
        "Map the CURRENT TRANSACTION and CUSTOMER ACTIVITY to the RED-FLAG CATALOG.\n"
        "Reply with ONLY compact JSON, no markdown.\n"
        "Schema:\n"
        '{"matched_rule_codes": string[], "additional_suspicions": [{"title": string, "summary": string, '
        '"rationale": string}], "request_edd": boolean}\n'
        "Rules:\n"
        "- matched_rule_codes: use ONLY exact rule_code strings copied from the CATALOG list below. "
        "Choose rules whose regulatory description fits the behaviour, remarks, narration, velocity, "
        "counterparties, or activity summary — even when keywords did not trigger automated matching.\n"
        "- If nothing in the catalog fits but the activity is still suspicious, use additional_suspicions "
        "(max 2 items) with a short title and summary. Leave both arrays empty if activity appears routine.\n"
        "- Be conservative; do not invent rule_codes.\n"
        "- request_edd: true if purpose, source of funds, or destination needs customer clarification.\n"
    )

    exp_txt = f"{expected_annual_turnover:,.0f}" if expected_annual_turnover is not None else "(unknown)"
    user = (
        f"RED-FLAG CATALOG:\n{catalog_text}\n\n"
        f"KEYWORD-MATCHED RULE CODES (already fired by the engine — you may still add catalog codes "
        f"if semantics justify, or additional_suspicions for gaps):\n{pat_txt}\n\n"
        f"CUSTOMER: id={customer_id}, name={customer_name or '(unknown)'}, segment={kyc_segment or '(unknown)'}, "
        f"line_of_business={line_of_business or '(unknown)'}, declared_expected_annual_turnover_ngn={exp_txt}\n"
        f"OFFICER/CUSTOMER REMARKS ON FILE:\n{customer_remarks or '(none)'}\n\n"
        f"CUSTOMER ACTIVITY SUMMARY:\n{activity}\n\n"
        f"CURRENT TRANSACTION JSON:\n{json.dumps(txn, default=str)[:7000]}\n"
    )

    try:
        client = get_llm_client()
        result = await client.generate(user, system=system, temperature=0.12)
    except Exception:
        log.exception("red_flag_llm_client_failed")
        return []

    data = _extract_json_object(result.content)
    if not isinstance(data, dict):
        return []

    raw_codes = data.get("matched_rule_codes")
    codes: List[str] = []
    seen_code_l: Set[str] = set()
    if isinstance(raw_codes, list):
        for c in raw_codes:
            key = str(c).strip().lower()
            row_c = code_to_row.get(key)
            if not row_c:
                key2 = _norm_catalog_code(str(c))
                row_c = code_to_row.get(key2)
            if not row_c:
                continue
            canonical = str(row_c.get("rule_code") or "").strip()
            if canonical.lower() in seen_code_l:
                continue
            seen_code_l.add(canonical.lower())
            codes.append(canonical)

    add_raw = data.get("additional_suspicions")
    additions: List[Dict[str, Any]] = []
    if isinstance(add_raw, list):
        for item in add_raw[:2]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            rationale = str(item.get("rationale") or "").strip()
            if not title and not summary:
                continue
            additions.append({"title": title or "AI suspicion", "summary": summary, "rationale": rationale})

    req_edd = bool(data.get("request_edd"))

    hits: List[TypologyHit] = []
    seen: Set[str] = set()
    for rc in codes:
        row = code_to_row.get(str(rc).strip().lower())
        if not row:
            continue
        canonical = str(row.get("rule_code") or rc).strip()
        rid = f"RF-{canonical}"
        if rid in seen:
            continue
        seen.add(rid)
        tit = str(row.get("title") or canonical)
        desc = str(row.get("description") or "")
        nar = f"[AI catalog mapping] {desc[:520]}"
        if len(nar) > 880:
            nar = nar[:880] + "…"
        hits.append(
            TypologyHit(
                rule_id=rid,
                title=f"{tit} (AI-matched)",
                narrative=nar,
                nfiu_reference="Configurable red flag",
            )
        )

    for item in additions:
        title = item.get("title") or "Emergent risk"
        summary = item.get("summary") or ""
        rationale = item.get("rationale") or ""
        hkey = hashlib.sha256(f"{title}|{summary}".encode("utf-8")).hexdigest()[:12]
        rid = f"RF-AI-EXT-{hkey}"
        if rid in seen:
            continue
        seen.add(rid)
        body = summary
        if rationale:
            body = f"{summary} Rationale: {rationale}"
        hits.append(
            TypologyHit(
                rule_id=rid,
                title=str(title)[:200],
                narrative=(body[:900] if body else str(title))[:900],
                nfiu_reference="AI-derived suspicion",
            )
        )

    if req_edd:
        rid_edd = "RF-AI-EDD"
        if rid_edd not in seen:
            seen.add(rid_edd)
            hits.append(
                TypologyHit(
                    rule_id=rid_edd,
                    title="AI: enhanced due diligence suggested",
                    narrative="The model flagged request_edd=true: clarify purpose, source of funds, or destination with the customer.",
                    nfiu_reference="EDD / customer clarification",
                )
            )

    if settings.aml_red_flag_ai_observation_log and pg is not None and (codes or additions or req_edd):
        try:
            from app.services.red_flag_ai_observations_db import insert_observation

            await insert_observation(
                pg,
                transaction_id=transaction_id,
                customer_id=customer_id,
                matched_rule_codes=codes,
                additional_suspicions=additions,
                pattern_matched_rule_codes=pat,
                request_edd=req_edd,
                model_provider=getattr(result, "provider", None),
            )
        except Exception:
            log.exception("red_flag_ai_observation_log_failed")

    return hits
