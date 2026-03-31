from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set

from app.services.transaction_analytics import _is_inflow, _is_outflow, _txn_ts


@dataclass(frozen=True)
class TypologyHit:
    rule_id: str
    title: str
    narrative: str
    nfiu_reference: str  # typology bucket for filing narrative


CRYPTO_KEYWORDS = re.compile(
    r"\b(btc|eth|ethereum|bitcoin|crypto|bnb|usdt|usdc|lama|defi|nft|binance|wallet\s*addr)\b",
    re.I,
)
GOV_KEYWORDS = re.compile(
    r"\b(gov\.?|government|federal\s+ministry|state\s+ministry|ministry\s+of|agency|firs|nipc|cbn\s+refund|treasury)\b",
    re.I,
)
HIGH_RISK_NARRATIVE = re.compile(
    r"\b(weapon|explosive|contraband|fentanyl|precursor|chemical\s+weapon|wmd)\b",
    re.I,
)
TRAFFICKING_NARRATIVE = re.compile(
    r"\b(kidnap|kidnapping|traffick|organ\s+harvest|dialysis|kidney|transplant|sex\s+work|prostitution)\b",
    re.I,
)
PEP_HINT = re.compile(r"\b(pep|politically\s+exposed|senator|honourable|governor|minister)\b", re.I)
SANCTIONS_JURISDICTION = re.compile(
    r"\b(iran|north\s+korea|dprk|syria|crimea|donetsk|luhansk|belarus|myanmar|afghanistan\s+taliban)\b",
    re.I,
)

# Profile vs narrative mismatch (illustrative lexicons for demo narratives)
PROFILE_KEYWORDS = {
    "tailor": ["building contract", "construction", "solar installation", "civil works", "road contract"],
    "plumber": ["solar", "building contract", "mining", "oil bloc"],
    "student": ["salary payment 50", "payroll bulk", "dividend", "consulting fee usd"],
    "civil servant": ["shell company", "offshore", "crypto mining"],
}


def _baseline_amounts(baseline: Sequence[Dict[str, Any]]) -> List[float]:
    return [float(t.get("amount") or 0.0) for t in baseline]


def _distinct_counterparties(txns: List[Dict[str, Any]], *, inflow_only: bool) -> Set[str]:
    out: Set[str] = set()
    for t in txns:
        if inflow_only and not _is_inflow(t):
            continue
        if not inflow_only and not _is_outflow(t):
            continue
        cp = str(t.get("counterparty_id") or "").strip()
        if cp:
            out.add(cp)
    return out


def _structuring_hint(txns: List[Dict[str, Any]], window_hours: int = 48) -> bool:
    """Several similar small credits in a short window (demo heuristic)."""
    if len(txns) < 3:
        return False
    now = _txn_ts(txns[-1])
    start = now - timedelta(hours=window_hours)
    small: List[float] = []
    for t in txns:
        if not _is_inflow(t):
            continue
        if _txn_ts(t) < start:
            continue
        a = float(t.get("amount") or 0)
        if 10_000 <= a <= 900_000:
            small.append(a)
    if len(small) < 3:
        return False
    total = sum(small)
    if total <= 0:
        return False
    return all(x <= total * 0.35 for x in small)


def evaluate_typologies(
    txn: Dict[str, Any],
    baseline_txns: Sequence[Dict[str, Any]],
    *,
    customer_profile_label: Optional[str] = None,
) -> List[TypologyHit]:
    """
    Rule-based AML typology hints aligned with common ML scenarios and NFIU narrative themes.
    Complements statistical anomaly detection (Isolation Forest).
    """
    hits: List[TypologyHit] = []
    narrative = f"{txn.get('narrative') or ''} {txn.get('remarks') or ''}"
    meta = txn.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    amt = float(txn.get("amount") or 0.0)
    cp_name = str(txn.get("counterparty_name") or meta.get("counterparty_name") or "")
    cp_id = str(txn.get("counterparty_id") or meta.get("counterparty_id") or "")
    channel = str(meta.get("channel") or txn.get("channel") or "")

    baseline_list = list(baseline_txns)
    amounts = _baseline_amounts(baseline_list)
    max_prior = max(amounts) if amounts else 0.0

    # 7 First-time or step-change large movement
    if amt >= 1_000_000 and max_prior > 0 and amt > max_prior * 5:
        hits.append(
            TypologyHit(
                rule_id="TYP-FIRST-HUGE",
                title="Unusual magnitude vs customer history",
                narrative=(
                    f"The amount (₦{amt:,.0f}) materially exceeds prior single transactions on this relationship "
                    f"(prior maximum approximately ₦{max_prior:,.0f}), consistent with first-time or step-change flows."
                ),
                nfiu_reference="Unusual transaction size / velocity",
            )
        )

    # 13 Sudden movement (velocity in 24h window same customer)
    ts0 = _txn_ts(txn)
    day_start = ts0 - timedelta(hours=24)
    recent = [t for t in baseline_list + [txn] if _txn_ts(t) >= day_start]
    vol24 = sum(float(t.get("amount") or 0) for t in recent)
    if vol24 >= amt * 2 and amt >= 500_000:
        hits.append(
            TypologyHit(
                rule_id="TYP-SUDDEN-MOVEMENT",
                title="Sudden movement / velocity cluster",
                narrative=(
                    f"Aggregate customer throughput in the 24-hour window exceeds ₦{vol24:,.0f}, "
                    "indicating compressed activity that may warrant layering review."
                ),
                nfiu_reference="Rapid movement of funds",
            )
        )

    # 1 Fan-in: multiple sources to one account (baseline window)
    window_start = ts0 - timedelta(days=30)
    window_tx = [t for t in baseline_list if _txn_ts(t) >= window_start] + [txn]
    ins = _distinct_counterparties(window_tx, inflow_only=True)
    if len(ins) >= 3 and _is_inflow(txn):
        hits.append(
            TypologyHit(
                rule_id="TYP-FAN-IN",
                title="Multiple inbound sources (consolidation)",
                narrative=(
                    f"Within 30 days, inflows were observed from {len(ins)} distinct counterparties, "
                    "a pattern sometimes associated with aggregation or placement."
                ),
                nfiu_reference="Multiple sources to single beneficiary",
            )
        )

    # 2 Fan-out
    outs = _distinct_counterparties(window_tx, inflow_only=False)
    if len(outs) >= 3 and _is_outflow(txn):
        hits.append(
            TypologyHit(
                rule_id="TYP-FAN-OUT",
                title="Multiple outbound destinations",
                narrative=(
                    f"Within 30 days, outflows were directed to {len(outs)} distinct counterparties, "
                    "consistent with distribution or layering typologies."
                ),
                nfiu_reference="Single source to multiple beneficiaries",
            )
        )

    # 3 Structuring-style inflows
    if _structuring_hint(window_tx):
        hits.append(
            TypologyHit(
                rule_id="TYP-STRUCTURING",
                title="Structured or split inflows (heuristic)",
                narrative=(
                    "Several inbound credits of similar magnitude occurred in a short period without clear "
                    "economic explanation, warranting review for structuring indicators."
                ),
                nfiu_reference="Structuring / smurfing",
            )
        )

    # 4 Company to individual (metadata hint)
    if meta.get("counterparty_type") == "company" or "LTD" in cp_name.upper() or "PLC" in cp_name.upper():
        if _is_inflow(txn) and "retail" in str(meta.get("customer_segment") or "").lower():
            hits.append(
                TypologyHit(
                    rule_id="TYP-CORP-TO-INDIVIDUAL",
                    title="Corporate counterparty to individual account",
                    narrative=(
                        "Inbound flow involves a corporate-typed counterparty crediting an individual relationship; "
                        "verify underlying contract and beneficial ownership."
                    ),
                    nfiu_reference="Corporate payments to individuals",
                )
            )

    # 5 Government-style narrative
    if GOV_KEYWORDS.search(narrative) or GOV_KEYWORDS.search(cp_name):
        hits.append(
            TypologyHit(
                rule_id="TYP-GOV-FLOW",
                title="Public-sector themed reference",
                narrative=(
                    "Transaction narrative or counterparty references public-sector or ministry themes; "
                    "confirm authenticity and appropriateness for an individual account."
                ),
                nfiu_reference="Government-related flows",
            )
        )

    # 6 Profile / narrative mismatch
    plabel = (customer_profile_label or meta.get("profile") or meta.get("pattern") or "").lower()
    for prof, bad_terms in PROFILE_KEYWORDS.items():
        if prof in plabel:
            for term in bad_terms:
                if term.lower() in narrative.lower():
                    hits.append(
                        TypologyHit(
                            rule_id="TYP-PROFILE-MISMATCH",
                            title="Occupation / narrative inconsistency",
                            narrative=(
                                f"The customer profile suggests “{prof}” while the narration references “{term}”, "
                                "which may indicate mis-declared economic purpose."
                            ),
                            nfiu_reference="Economic purpose inconsistency",
                        )
                    )
                    break

    # 8–9 YTD vs expected (metadata expected_annual_turnover)
    expected = meta.get("expected_annual_turnover") or meta.get("expected_monthly_lodgment")
    if expected is not None:
        try:
            exp = float(expected)
            if exp > 0 and amt > exp * 3:
                hits.append(
                    TypologyHit(
                        rule_id="TYP-EXPECTED-TURNOVER",
                        title="Turnover vs declared expectation",
                        narrative=(
                            f"Transaction size is large relative to declared expectation in KYC metadata "
                            f"(₦{amt:,.0f} vs reference ₦{exp:,.0f}); review source of funds."
                        ),
                        nfiu_reference="Turnover inconsistent with profile",
                    )
                )
        except (TypeError, ValueError):
            pass

    # 10 Crypto / high-risk keywords
    if CRYPTO_KEYWORDS.search(narrative):
        hits.append(
            TypologyHit(
                rule_id="TYP-CRYPTO-KEYWORD",
                title="Virtual asset / crypto reference in narration",
                narrative=(
                    "Narration contains virtual-asset or crypto-related wording; assess VA exposure and travel rule data."
                ),
                nfiu_reference="Virtual assets",
            )
        )

    # 11 Individual account running payroll-like behaviour
    if any(k in narrative.lower() for k in ("salary", "payroll", "staff pay", "remittance bulk")):
        if "individual" in plabel or meta.get("account_class") == "individual":
            hits.append(
                TypologyHit(
                    rule_id="TYP-INDIV-PAYROLL",
                    title="Payroll-like flows on individual account",
                    narrative=(
                        "Narration suggests payroll or bulk staff payments through an individual account; "
                        "verify if a corporate account should be used."
                    ),
                    nfiu_reference="Misuse of personal account for business",
                )
            )

    # 12 Wallet / investment channel hopping
    if any(k in channel.lower() for k in ("wallet", "investment", "savings sweep", "liquidity")):
        hits.append(
            TypologyHit(
                rule_id="TYP-CHANNEL-HOP",
                title="Inter-account / wallet movement",
                narrative=(
                    "Channel metadata suggests movement between wallet, investment, or savings buckets; "
                    "map full funds trail for layering indicators."
                ),
                nfiu_reference="Layering across accounts/products",
            )
        )

    # 14 Pricing / trade anomaly (keyword)
    if re.search(r"\b(below\s+cost|above\s+market|invoice\s+inflated|discount\s+\d{2,}%)\b", narrative, re.I):
        hits.append(
            TypologyHit(
                rule_id="TYP-TRADE-PRICING",
                title="Trade pricing anomaly (narrative)",
                narrative="Narration hints at non-market pricing; review trade documentation and counterparties.",
                nfiu_reference="Trade-based ML",
            )
        )

    # 15–16 Sensitive goods / medical / trafficking wording
    if HIGH_RISK_NARRATIVE.search(narrative):
        hits.append(
            TypologyHit(
                rule_id="TYP-SENSITIVE-GOODS",
                title="Sensitive goods wording",
                narrative="Narration references controlled or sensitive goods categories; escalate per policy.",
                nfiu_reference="Proliferation / controlled goods",
            )
        )
    if TRAFFICKING_NARRATIVE.search(narrative):
        hits.append(
            TypologyHit(
                rule_id="TYP-TRAFFICKING-KEYWORD",
                title="High-risk human-security wording",
                narrative="Narration references medical/trafficking themes; requires enhanced review and possible STR.",
                nfiu_reference="Human trafficking / medical abuse",
            )
        )

    # 17 PEP
    if PEP_HINT.search(narrative) or PEP_HINT.search(cp_name) or meta.get("pep_flag") is True:
        hits.append(
            TypologyHit(
                rule_id="TYP-PEP",
                title="PEP exposure (indicator)",
                narrative="PEP indicators present in metadata or text; apply PEP escalation and source-of-wealth review.",
                nfiu_reference="PEP",
            )
        )

    # 18 Sanctions jurisdiction hint in narrative (full screening separate)
    if SANCTIONS_JURISDICTION.search(narrative) or SANCTIONS_JURISDICTION.search(cp_name):
        hits.append(
            TypologyHit(
                rule_id="TYP-SANCTIONS-JURISDICTION",
                title="High-risk jurisdiction reference",
                narrative="Narration or counterparty references high-risk jurisdictions; cross-check sanctions lists.",
                nfiu_reference="Sanctions / high-risk jurisdiction",
            )
        )

    # De-duplicate by rule_id (keep first narrative)
    seen: Set[str] = set()
    unique: List[TypologyHit] = []
    for h in hits:
        if h.rule_id in seen:
            continue
        seen.add(h.rule_id)
        unique.append(h)
    return unique


def typology_narrative_block(hits: Sequence[TypologyHit]) -> str:
    if not hits:
        return (
            "Automated typology review did not add supplementary rules beyond statistical scoring; "
            "analyst judgement remains essential."
        )
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(f"{i}. [{h.rule_id}] {h.title}: {h.narrative} (NFIU theme: {h.nfiu_reference}).")
    return " ".join(parts)
