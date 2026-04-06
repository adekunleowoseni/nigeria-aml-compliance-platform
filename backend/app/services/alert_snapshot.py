from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, List, Optional

from app.config import settings
from app.core.logging import get_logger
from app.db.postgres_client import PostgresClient
from app.models.alert import AlertResponse
from app.services.llm.client import GeminiClient, get_llm_client
from app.services.customer_kyc_db import get_or_create_customer_kyc, list_bvn_linked_accounts
from app.services.reference_lists_service import screen_customer_name
from app.services.sanctions_screening import screen_name_opensanctions
from app.services.transaction_analytics import (
    CounterpartyFlow,
    _is_inflow,
    _is_outflow,
    _txn_ts,
    adverse_media_placeholder,
    aggregate_counterparty_flows,
    assess_funds_utilization,
    compute_flow_metrics,
    ytd_calendar_year_inflow_ngn,
)
from app.services.red_flag_ai_matcher import run_red_flag_llm_matcher
from app.services.red_flag_rules_service import evaluate_custom_red_flags
from app.services.typology_rules import (
    TypologyHit,
    dedupe_typology_hits,
    evaluate_typologies,
    typology_narrative_block,
)

log = get_logger(component="alert_snapshot")


def _debit_credit(txn: Dict[str, Any]) -> str:
    from app.services.transaction_analytics import _is_inflow, _is_outflow

    if _is_outflow(txn):
        return "Debit (outflow)"
    if _is_inflow(txn):
        return "Credit (inflow)"
    return "Unclassified"


def _serialize_kyc(kyc: Any) -> Dict[str, Any]:
    return {
        "customer_name": kyc.customer_name,
        "account_number": kyc.account_number,
        "account_opened": kyc.account_opened.isoformat(),
        "customer_address": kyc.customer_address,
        "line_of_business": kyc.line_of_business,
        "phone_number": kyc.phone_number,
        "date_of_birth": kyc.date_of_birth.isoformat(),
        "id_number": kyc.id_number,
        "bvn": kyc.id_number,
    }


def _contact_email_for_snapshot(customer_id: str, txn_dict: Dict[str, Any]) -> str:
    """
    On-file email for EDD workflows: prefer transaction metadata, else a stable demo address.
    Replace with the customer's real address before sending live mail.
    """
    md = txn_dict.get("metadata") if isinstance(txn_dict.get("metadata"), dict) else {}
    for key in ("customer_email", "contact_email", "email"):
        raw = md.get(key)
        if isinstance(raw, str) and "@" in raw.strip():
            return raw.strip()
    slug = "".join(c for c in (customer_id or "customer") if c.isalnum() or c in "-_")
    slug = (slug or "customer").lower()
    return f"{slug}@example.com"


def _hits_to_dict(hits: List[TypologyHit]) -> List[Dict[str, str]]:
    return [
        {"rule_id": h.rule_id, "title": h.title, "narrative": h.narrative, "nfiu_reference": h.nfiu_reference}
        for h in hits
    ]


def _summarize_notable_outbound_24h(
    customer_id: str,
    all_txn_dicts: List[Dict[str, Any]],
    *,
    as_of: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Build notable outbound destinations list from the 24h window ending at as_of (flagged txn time by default).
    Excludes very small flows unless they appear as structuring-like repeats.
    """
    end = as_of if as_of is not None else datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - timedelta(hours=24)
    grouped: Dict[str, Dict[str, Any]] = {}

    for t in all_txn_dicts:
        if str(t.get("customer_id") or "") != customer_id:
            continue
        if not _is_outflow(t):
            continue
        ts = _txn_ts(t)
        if ts < start:
            continue

        meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        cpid = str(t.get("counterparty_id") or meta.get("counterparty_id") or "UNKNOWN").strip() or "UNKNOWN"
        cpname = t.get("counterparty_name") or meta.get("counterparty_name")
        bank = meta.get("sender_bank") or meta.get("bank") or meta.get("institution")
        amt = float(t.get("amount") or 0.0)

        row = grouped.setdefault(
            cpid,
            {"counterparty_id": cpid, "counterparty_name": cpname, "bank_or_institution": bank, "total_amount": 0.0, "txn_count": 0},
        )
        row["total_amount"] += amt
        row["txn_count"] += 1
        row["counterparty_name"] = row["counterparty_name"] or cpname
        row["bank_or_institution"] = row["bank_or_institution"] or bank

    notable: List[CounterpartyFlow] = []
    for v in grouped.values():
        total = float(v.get("total_amount") or 0.0)
        n = int(v.get("txn_count") or 0)
        # Keep only material outflows or structuring-like repeated small debits.
        if total >= 100_000 or n >= 3:
            notable.append(
                CounterpartyFlow(
                    direction="outbound",
                    counterparty_id=str(v.get("counterparty_id") or "UNKNOWN"),
                    counterparty_name=v.get("counterparty_name"),
                    bank_or_institution=v.get("bank_or_institution"),
                    total_amount=total,
                    txn_count=n,
                )
            )

    notable.sort(key=lambda x: x.total_amount, reverse=True)
    return [asdict(x) for x in notable[:8]]


def _summarize_inbound_sources_24h(
    customer_id: str,
    all_txn_dicts: List[Dict[str, Any]],
    *,
    as_of: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Group credit (inflow) transactions in the 24h window ending at as_of by counterparty for STR Word layout."""
    end = as_of if as_of is not None else datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - timedelta(hours=24)
    grouped: Dict[str, Dict[str, Any]] = {}

    for t in all_txn_dicts:
        if str(t.get("customer_id") or "") != customer_id:
            continue
        if not _is_inflow(t):
            continue
        ts = _txn_ts(t)
        if ts < start:
            continue

        meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        cpid = str(t.get("counterparty_id") or meta.get("counterparty_id") or "UNKNOWN").strip() or "UNKNOWN"
        cpname = t.get("counterparty_name") or meta.get("counterparty_name")
        bank = meta.get("sender_bank") or meta.get("originating_bank") or meta.get("bank") or meta.get("institution")
        amt = float(t.get("amount") or 0.0)
        if amt <= 0:
            continue

        row = grouped.setdefault(
            cpid,
            {
                "counterparty_id": cpid,
                "counterparty_name": cpname,
                "bank_or_institution": bank,
                "total_amount": 0.0,
                "txn_count": 0,
                "sample_narrative": "",
            },
        )
        row["total_amount"] += amt
        row["txn_count"] += 1
        row["counterparty_name"] = row["counterparty_name"] or cpname
        row["bank_or_institution"] = row["bank_or_institution"] or bank
        if not row["sample_narrative"] and t.get("narrative"):
            row["sample_narrative"] = str(t.get("narrative") or "")[:500]

    rows = list(grouped.values())
    rows.sort(key=lambda x: float(x.get("total_amount") or 0.0), reverse=True)
    return rows[:12]


def _summarize_outbound_destinations_24h_all(
    customer_id: str,
    all_txn_dicts: List[Dict[str, Any]],
    *,
    as_of: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """All outflow counterparties in the 24h window ending at as_of (STR single vs multiple beneficiary logic)."""
    end = as_of if as_of is not None else datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - timedelta(hours=24)
    grouped: Dict[str, Dict[str, Any]] = {}

    for t in all_txn_dicts:
        if str(t.get("customer_id") or "") != customer_id:
            continue
        if not _is_outflow(t):
            continue
        ts = _txn_ts(t)
        if ts < start:
            continue

        meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        cpid = str(t.get("counterparty_id") or meta.get("counterparty_id") or "UNKNOWN").strip() or "UNKNOWN"
        cpname = t.get("counterparty_name") or meta.get("counterparty_name")
        bank = meta.get("beneficiary_bank") or meta.get("receiver_bank") or meta.get("bank") or meta.get("institution")
        amt = float(t.get("amount") or 0.0)
        if amt <= 0:
            continue

        row = grouped.setdefault(
            cpid,
            {
                "counterparty_id": cpid,
                "counterparty_name": cpname,
                "bank_or_institution": bank,
                "total_amount": 0.0,
                "txn_count": 0,
                "sample_narrative": "",
            },
        )
        row["total_amount"] += amt
        row["txn_count"] += 1
        row["counterparty_name"] = row["counterparty_name"] or cpname
        row["bank_or_institution"] = row["bank_or_institution"] or bank
        if not row["sample_narrative"] and t.get("narrative"):
            row["sample_narrative"] = str(t.get("narrative") or "")[:500]

    rows = list(grouped.values())
    rows.sort(key=lambda x: float(x.get("total_amount") or 0.0), reverse=True)
    return rows[:12]


def _max_prior_single_transaction_amount(
    customer_id: str, all_txn_dicts: List[Dict[str, Any]], exclude_txn_id: Optional[str] = None
) -> float:
    m = 0.0
    for t in all_txn_dicts:
        if str(t.get("customer_id") or "") != customer_id:
            continue
        if exclude_txn_id and str(t.get("id") or "") == str(exclude_txn_id):
            continue
        m = max(m, float(t.get("amount") or 0.0))
    return m


def _build_llm_prompt(
    *,
    customer_name: str,
    typology_lines: List[str],
    outbound_24h: List[Dict[str, Any]],
    sanctions: Dict[str, Any],
    fallback_adverse_note: str,
) -> str:
    return (
        "You are an AML compliance analyst writing concise STR supporting context for Nigeria goAML.\n"
        "Write plain English only. Do NOT include internal rule IDs/codes like [TYP-...].\n"
        "Return exactly three short paragraphs with these headings:\n"
        "1) Additional context summary\n"
        "2) Adverse media note\n"
        "3) Sanctions screening note\n\n"
        "Requirements:\n"
        "- Additional context summary must focus on notable outbound (outflow) destinations in the last 24 hours only.\n"
        "- Mention counterparty and amount where available.\n"
        "- Exclude small-value purchases/noise unless pattern suggests structuring.\n"
        "- Be compliance-neutral: state observations and required manual verification, no final legal conclusion.\n\n"
        f"Customer: {customer_name}\n"
        f"Typology observations (human-readable): {typology_lines}\n"
        f"Notable 24h outbound destinations: {outbound_24h}\n"
        f"Sanctions screening raw: {sanctions}\n"
        f"Fallback adverse note: {fallback_adverse_note}\n"
    )


async def _gemini_enrichment_notes(
    *,
    customer_name: str,
    typology_lines: List[str],
    outbound_24h: List[Dict[str, Any]],
    sanctions: Dict[str, Any],
    fallback_adverse_note: str,
) -> Dict[str, str]:
    prompt = _build_llm_prompt(
        customer_name=customer_name,
        typology_lines=typology_lines,
        outbound_24h=outbound_24h,
        sanctions=sanctions,
        fallback_adverse_note=fallback_adverse_note,
    )
    system = "You write concise AML STR narrative supplements for compliance teams."

    try:
        # Prefer Gemini directly when configured.
        from app.config import settings

        if settings.gemini_api_key:
            client = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
        else:
            client = get_llm_client()
        result = await client.generate(prompt=prompt, system=system)
        content = (result.content or "").strip()
        if content:
            return {"combined": content}
    except Exception:
        log.exception("gemini_enrichment_generation_failed")

    # Deterministic fallback.
    sanctions_count = int(sanctions.get("match_count") or 0)
    adverse = fallback_adverse_note
    screening = (
        f"Online sanctions/watchlist screening returned {sanctions_count} potential match(es); manual adjudication is required."
        if sanctions_count > 0
        else "Online sanctions screening returned no direct match at this time; this is not a clearance and requires analyst validation."
    )
    outbound_bits = []
    for row in outbound_24h[:4]:
        outbound_bits.append(
            f"{row.get('counterparty_name') or row.get('counterparty_id')} (₦{float(row.get('total_amount') or 0):,.0f})"
        )
    context = (
        "Additional context summary\n"
        + (
            f"Within the last 24 hours, notable outbound destinations include: {', '.join(outbound_bits)}."
            if outbound_bits
            else "Within the last 24 hours, no material outbound (outflow) destination concentration was observed above the notable threshold."
        )
        + "\n\nAdverse media note\n"
        + adverse
        + "\n\nSanctions screening note\n"
        + screening
    )
    return {"combined": context}


def _kyc_documents_on_file(txn_dict: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Documents supplied for CCO escalation context. Uses txn metadata when present; else demo CDD pack labels.
    """
    md = txn_dict.get("metadata") if isinstance(txn_dict.get("metadata"), dict) else {}
    raw = md.get("documents_supplied")
    rows: List[Dict[str, str]] = []
    if isinstance(raw, list):
        for x in raw:
            rows.append({"label": str(x), "status": "Captured with filing / branch intake"})
    elif isinstance(raw, str) and raw.strip():
        rows.append({"label": raw.strip(), "status": "As declared at branch"})
    if not rows:
        rows = [
            {"label": "Government-issued ID (BVN / NIN verification)", "status": "On file — KYC record"},
            {"label": "Proof of address", "status": "Standard CDD pack (demo)"},
            {"label": "Risk rating / PEP screening worksheet", "status": "Per institution policy (demo)"},
        ]
    return rows


def _extract_llm_section(text: str, heading: str) -> str:
    if not text.strip():
        return ""
    pattern = re.compile(
        rf"(?is){re.escape(heading)}\s*\n(.*?)(?=\n\s*(Additional context summary|Adverse media note|Sanctions screening note)\s*\n|$)"
    )
    m = pattern.search(text)
    if not m:
        return ""
    return re.sub(r"\s+", " ", (m.group(1) or "").strip())


async def build_alert_snapshot(
    *,
    alert: AlertResponse,
    txn: Optional[Dict[str, Any]],
    all_txn_dicts: List[Dict[str, Any]],
    pg: Optional[PostgresClient],
) -> Dict[str, Any]:
    """
    Pre-resolution view: transaction, customer, windows (24h / 12m / lifetime), typologies,
    counterparty flows, sanctions screening, BVN-linked accounts, funds utilisation narrative.
    """
    txn_dict = txn or {
        "id": alert.transaction_id,
        "customer_id": alert.customer_id,
        "amount": 0.0,
        "currency": "NGN",
        "transaction_type": "unknown",
        "narrative": alert.summary,
        "metadata": {},
        "created_at": datetime.utcnow().isoformat(),
    }

    cid = alert.customer_id
    baseline = [t for t in all_txn_dicts if str(t.get("customer_id")) == cid and str(t.get("id")) != str(txn_dict.get("id"))]

    profile_label = ""
    md = txn_dict.get("metadata") or {}
    if isinstance(md, dict):
        profile_label = str(md.get("profile") or md.get("pattern") or "")

    kyc = await get_or_create_customer_kyc(pg, cid, txn_dict)
    ytd_ngn = ytd_calendar_year_inflow_ngn(cid, baseline, txn_dict)
    typ_hits = evaluate_typologies(
        txn_dict,
        baseline,
        customer_profile_label=profile_label,
        kyc_segment=kyc.customer_segment,
        expected_annual_turnover=kyc.expected_annual_turnover,
        customer_remarks=kyc.customer_remarks,
        ytd_inflow_total_ngn=ytd_ngn,
        line_of_business=kyc.line_of_business,
    )
    rf_hits = await evaluate_custom_red_flags(
        pg,
        txn_dict,
        customer_remarks=kyc.customer_remarks or "",
        line_of_business=kyc.line_of_business or "",
    )
    typ_hits = dedupe_typology_hits(list(typ_hits) + list(rf_hits))

    if pg is not None and settings.aml_red_flag_llm_on_snapshot:

        def _snapshot_pattern_rf_codes(hits_list: List[TypologyHit]) -> List[str]:
            out: List[str] = []
            for h in hits_list:
                rid = h.rule_id
                if not rid.startswith("RF-") or rid.startswith("RF-AI-"):
                    continue
                out.append(rid[3:])
            return out

        llm_rf_snap = await run_red_flag_llm_matcher(
            pg,
            txn_dict,
            baseline,
            customer_id=cid,
            customer_remarks=kyc.customer_remarks or "",
            line_of_business=kyc.line_of_business or "",
            kyc_segment=kyc.customer_segment or "",
            expected_annual_turnover=kyc.expected_annual_turnover,
            customer_name=kyc.customer_name or "",
            pattern_matched_rule_codes=_snapshot_pattern_rf_codes(rf_hits),
            transaction_id=str(txn_dict.get("id") or alert.transaction_id or ""),
        )
        typ_hits = dedupe_typology_hits(list(typ_hits) + list(llm_rf_snap))

    flag_ts = _txn_ts(txn_dict)
    metrics = compute_flow_metrics(cid, all_txn_dicts, as_of=flag_ts)
    _, outbound = aggregate_counterparty_flows(cid, all_txn_dicts)
    bvn_accounts = await list_bvn_linked_accounts(pg, kyc.id_number, primary_customer_id=cid)

    sanctions = await screen_name_opensanctions(kyc.customer_name)
    sanctions = dict(sanctions)
    ref_screen = screen_customer_name(kyc.customer_name)
    ref_san_n = len(ref_screen["sanctions"])
    ref_pep_n = len(ref_screen["pep"])
    ref_am = ref_screen["adverse_media"]
    ref_am_n = len(ref_am)
    sanctions["reference_lists"] = {
        "fuzzy_threshold": ref_screen["fuzzy_threshold"],
        "sanctions_hits": ref_screen["sanctions"][:15],
        "pep_hits": ref_screen["pep"][:15],
    }
    sanctions["reference_list_match_count"] = ref_san_n + ref_pep_n
    sanctions["combined_screening_match_count"] = int(sanctions.get("match_count") or 0) + ref_san_n + ref_pep_n

    san_count = int(sanctions.get("match_count") or 0)
    combined_san_pep = san_count + ref_san_n + ref_pep_n
    outbound_24h_notable = _summarize_notable_outbound_24h(cid, all_txn_dicts, as_of=flag_ts)
    inbound_24h = _summarize_inbound_sources_24h(cid, all_txn_dicts, as_of=flag_ts)
    outbound_24h_all = _summarize_outbound_destinations_24h_all(cid, all_txn_dicts, as_of=flag_ts)
    prior_max_txn = _max_prior_single_transaction_amount(cid, all_txn_dicts, exclude_txn_id=str(txn_dict.get("id") or ""))
    llm_enrichment = await _gemini_enrichment_notes(
        customer_name=kyc.customer_name,
        typology_lines=[h.narrative for h in typ_hits][:6],
        outbound_24h=outbound_24h_notable,
        sanctions=sanctions,
        fallback_adverse_note=adverse_media_placeholder(kyc.customer_name, combined_san_pep),
    )
    llm_combined = (llm_enrichment.get("combined") or "").strip()
    llm_adverse_note = _extract_llm_section(llm_combined, "Adverse media note")
    llm_sanctions_note = _extract_llm_section(llm_combined, "Sanctions screening note")

    fallback_adverse = (
        "Automated screening did not return a direct adverse-media hit at the time of review; this is not a regulatory clearance."
        " Manual adverse-media and related-name validation is still required."
    )
    ref_note_pep = (
        f" Internal reference PEP list: {ref_pep_n} fuzzy match(es) at score ≥ {ref_screen['fuzzy_threshold']}."
        if ref_pep_n
        else ""
    )
    ref_note_san = (
        f" Internal reference sanctions list: {ref_san_n} fuzzy match(es) at score ≥ {ref_screen['fuzzy_threshold']}."
        if ref_san_n
        else ""
    )
    if combined_san_pep > 0:
        fallback_sanctions = (
            f"OpenSanctions returned {san_count} potential match(es); combined with internal reference lists "
            f"there are {combined_san_pep} name-related hit(s) requiring review.{ref_note_san}{ref_note_pep}"
        )
    else:
        fallback_sanctions = (
            "Online sanctions/watchlist screening returned no direct match at this time; this is not a clearance "
            "and analyst verification remains required."
        )

    funds = assess_funds_utilization(txn_dict, [t for t in all_txn_dicts if str(t.get("customer_id")) == cid])

    suspicion = {
        "anomaly_rules": list(alert.rule_ids or []),
        "typologies": _hits_to_dict(typ_hits),
        "summary_lines": [h.narrative for h in typ_hits][:6],
        "nfiu_narrative_addon": typology_narrative_block(typ_hits),
    }

    meta_tx = txn_dict.get("metadata") if isinstance(txn_dict.get("metadata"), dict) else {}
    cp_id = txn_dict.get("counterparty_id") or meta_tx.get("counterparty_id")
    cp_name = txn_dict.get("counterparty_name") or meta_tx.get("counterparty_name")

    customer_profile = _serialize_kyc(kyc)
    customer_profile["email"] = _contact_email_for_snapshot(cid, txn_dict)

    return {
        "alert_id": alert.id,
        "transaction": {
            "id": txn_dict.get("id"),
            "amount": txn_dict.get("amount"),
            "currency": txn_dict.get("currency") or "NGN",
            "transaction_type": txn_dict.get("transaction_type"),
            "debit_credit": _debit_credit(txn_dict),
            "narrative": txn_dict.get("narrative"),
            "created_at": txn_dict.get("created_at"),
            "counterparty_id": cp_id,
            "counterparty_name": cp_name,
            "metadata": txn_dict.get("metadata") or {},
        },
        "customer_profile": customer_profile,
        "kyc_documents_on_file": _kyc_documents_on_file(txn_dict),
        "bvn_linked_accounts": bvn_accounts,
        "why_suspicious": suspicion,
        "prior_max_single_transaction": prior_max_txn,
        "rolling_windows": {
            "real_time_note": "Rolling windows are anchored to the flagged transaction timestamp where applicable.",
            "last_24_hours": {
                "window_start": metrics.window_24h_start,
                "window_end": metrics.window_24h_end,
                "transaction_count": metrics.txn_count_24h,
                "inflow_total": metrics.inflow_24h,
                "outflow_total": metrics.outflow_24h,
            },
            "twelve_month_ytd": {
                "window_start": metrics.ytd_12m_start,
                "window_end": metrics.ytd_12m_end,
                "inflow_total": metrics.inflow_12m,
                "outflow_total": metrics.outflow_12m,
            },
            "lifetime_for_narrative": {
                "first_seen": metrics.lifetime_start,
                "account_age_days": metrics.account_age_days,
                "total_inflow": metrics.lifetime_inflow,
                "total_outflow": metrics.lifetime_outflow,
                "transaction_count": metrics.lifetime_txn_count,
            },
        },
        "flagged_flows": {
            # Keep this list scoped to notable outbound destinations in the last 24 hours for STR addendum.
            # (Key name preserved for backward compatibility in UI/report generators.)
            "top_inbound_sources": outbound_24h_notable,
            "top_outbound_destinations": [asdict(x) for x in outbound],
            "inbound_sources_24h": inbound_24h,
            "outbound_destinations_24h": outbound_24h_all,
        },
        "sanctions_screening": sanctions,
        "adverse_media": (
            adverse_media_placeholder(kyc.customer_name, combined_san_pep)
            + (
                f" Uploaded adverse-media reference list: {ref_am_n} fuzzy match(es) (threshold {ref_screen['fuzzy_threshold']})."
                if ref_am_n
                else ""
            )
        ),
        "reference_adverse_media_hits": ref_am[:15],
        "adverse_media_note": llm_adverse_note or fallback_adverse,
        "sanctions_screening_note": llm_sanctions_note or fallback_sanctions,
        "llm_additional_context": llm_enrichment.get("combined"),
        "funds_utilization": {
            "funds_utilized": funds.funds_utilized,
            "subsequent_outflow_total": funds.subsequent_outflow_total,
            "description": funds.description,
        },
        "severity": alert.severity,
        "status": alert.status,
    }
