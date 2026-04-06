from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, date, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from app.services.transaction_analytics import _is_inflow, _is_outflow


def _stable_rand(customer_id: str) -> int:
    h = hashlib.sha256(customer_id.encode("utf-8")).hexdigest()
    return int(h[:12], 16)


def _pick(items: list[str], idx: int) -> str:
    return items[idx % len(items)]


def _format_money(amount: float) -> str:
    # Template examples show no decimals for whole naira; keep that style.
    amt = int(round(amount))
    return f"{amt:,}"


def _format_money_2(amount: float) -> str:
    return f"{amount:,.2f}"


def _format_money_with_currency(amount: float) -> str:
    amt = int(round(amount))
    return f"₦{amt:,}"


_LESS_THAN_20 = [
    "Zero",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]

_TENS = {
    20: "Twenty",
    30: "Thirty",
    40: "Forty",
    50: "Fifty",
    60: "Sixty",
    70: "Seventy",
    80: "Eighty",
    90: "Ninety",
}


def _int_to_words_0_999(n: int) -> str:
    assert 0 <= n <= 999
    if n < 20:
        return _LESS_THAN_20[n]
    if n < 100:
        tens = (n // 10) * 10
        rem = n % 10
        if rem == 0:
            return _TENS[tens]
        return f"{_TENS[tens]} {_LESS_THAN_20[rem]}"
    hundreds = n // 100
    rem = n % 100
    if rem == 0:
        return f"{_LESS_THAN_20[hundreds]} Hundred"
    return f"{_LESS_THAN_20[hundreds]} Hundred and {_int_to_words_0_999(rem)}"


def _int_to_words(n: int) -> str:
    # Supports 0..999,999,999,999 (up to billions) which is enough for STR amounts.
    if n == 0:
        return "Zero"
    if n < 0:
        return f"Minus {_int_to_words(-n)}"

    billions = n // 1_000_000_000
    millions = (n // 1_000_000) % 1_000
    thousands = (n // 1_000) % 1_000
    remainder = n % 1_000

    parts: list[str] = []
    if billions:
        parts.append(f"{_int_to_words_0_999(billions)} Billion")
    if millions:
        parts.append(f"{_int_to_words_0_999(millions)} Million")
    if thousands:
        parts.append(f"{_int_to_words_0_999(thousands)} Thousand")
    if remainder:
        parts.append(_int_to_words_0_999(remainder))

    # Add commas like the sample: "Ninety Million, Fifty Five Thousand, One Hundred and ..."
    return ", ".join(parts)


def _amount_to_words(amount: float) -> str:
    total_cents = int(round(amount * 100))
    naira = total_cents // 100
    kobo = total_cents % 100
    if kobo == 0:
        return f"{_int_to_words(naira)} Naira"
    return f"{_int_to_words(naira)} Naira, {_int_to_words(kobo)} Kobo"


def _format_nigeria_phone(seed: int) -> str:
    # Generates 11-digit numbers like 08012345678
    prefixes = ["080", "081", "090", "091"]
    prefix = _pick(prefixes, seed)
    rest = seed % 10**8
    return f"{prefix}{rest:08d}"


def _format_bvn(seed: int) -> str:
    return f"{seed % 10**11:011d}"


def _format_account_number(seed: int) -> str:
    # 10-ish digits; goAML templates often accept 10–12 chars; keep simple.
    return f"{(seed % 10**10):010d}"


def _date_to_long(d: date) -> str:
    return d.strftime("%B %d, %Y")


def _month_day_year_from_seed(seed: int, start_year: int = 1980, end_year: int = 2015) -> date:
    year_range = max(1, end_year - start_year)
    year = start_year + (seed % year_range)
    month = 1 + ((seed // 7) % 12)
    # Keep day in a safe range (Word template doesn't care about exact day validity; still avoid invalid dates)
    day = 1 + ((seed // 13) % 28)
    return date(year, month, day)


@dataclass(frozen=True)
class CustomerKyc:
    customer_name: str
    account_number: str
    account_opened: date
    customer_address: str
    line_of_business: str
    phone_number: str
    date_of_birth: date
    id_number: str  # BVN / NIN-like placeholder
    customer_segment: str = "individual"  # individual | corporate
    expected_annual_turnover: Optional[float] = None
    customer_remarks: str = ""


def build_customer_kyc(
    customer_id: str,
    *,
    inferred_lob: Optional[str] = None,
    use_placeholders: bool = True,
) -> CustomerKyc:
    if use_placeholders:
        return CustomerKyc(
            customer_name="XXXXXXXXXXXX",
            account_number="XXXXXXXXXXX",
            account_opened=date(2010, 11, 19),
            customer_address="No. 5, Somorin Street, Obantoko, Abeokuta, Ogun State",
            line_of_business=inferred_lob or "Civil Servant",
            phone_number="XXXXXXXXXXXX",
            date_of_birth=date(1977, 9, 5),
            id_number="XXXXXXXXXXXXXX",
            customer_segment="individual",
            expected_annual_turnover=3_000_000.0,
            customer_remarks="",
        )
    seed = _stable_rand(customer_id)
    first_names = [
        "Amina",
        "Zainab",
        "Fatima",
        "Bola",
        "Ngozi",
        "Chinedu",
        "Ifunanya",
        "Toyin",
        "Rukayat",
        "Ibrahim",
        "Samuel",
        "Adaeze",
    ]
    last_names = [
        "Adeyemi",
        "Okafor",
        "Mohammed",
        "Lawal",
        "Abubakar",
        "Eze",
        "Oladipo",
        "Nwosu",
        "Mustapha",
        "Bello",
        "Babatunde",
        "Ibrahim",
    ]
    customer_name = f"{_pick(first_names, seed)} {_pick(last_names, seed // 3)}"

    account_opened = _month_day_year_from_seed(seed, start_year=2003, end_year=2016)
    dob = _month_day_year_from_seed(seed // 11, start_year=1965, end_year=1995)
    bvn = _format_bvn(seed // 17)
    account_number = _format_account_number(seed // 19)
    phone_number = _format_nigeria_phone(seed // 23)

    addresses = [
        "No. 5, Somorin Street, Obantoko, Abeokuta, Ogun State",
        "12, Unity Road, GRA Ikeja, Lagos State",
        "House 3, Market Road, Kaduna North, Kaduna State",
        "Plot 8, Riverside Estate, Port Harcourt, Rivers State",
        "No. 19, Unity Avenue, Benin City, Edo State",
    ]
    customer_address = _pick(addresses, seed // 29)

    default_lob = _pick(
        ["Civil Servant", "Student", "SME Trader", "Business Owner", "Merchant", "Logistics / Importer"],
        seed,
    )
    line_of_business = inferred_lob or default_lob

    segment = "corporate" if (seed // 11) % 7 == 0 else "individual"
    expected_turnover = float(1_200_000 + (seed % 180) * 45_000)

    return CustomerKyc(
        customer_name=customer_name,
        account_number=account_number,
        account_opened=account_opened,
        customer_address=customer_address,
        line_of_business=line_of_business,
        phone_number=phone_number,
        date_of_birth=dob,
        id_number=bvn,
        customer_segment=segment,
        expected_annual_turnover=expected_turnover * (2.2 if segment == "corporate" else 1.0),
        customer_remarks="",
    )


def infer_line_of_business_from_txn(txn: Dict[str, Any]) -> Optional[str]:
    """Infer LOB label from transaction metadata (simulation / profile hints)."""
    inferred_lob: Optional[str] = None
    meta = txn.get("metadata") or {}
    if isinstance(meta, dict):
        profile_label = meta.get("profile") or meta.get("pattern")
        if profile_label:
            pl = str(profile_label).lower()
            if "salary" in pl or "worker" in pl or "salaried" in pl:
                inferred_lob = "Civil Servant"
            elif "student" in pl:
                inferred_lob = "Student"
            elif "trader" in pl or "sme" in pl:
                inferred_lob = "SME Trader"
            elif "hnwi" in pl or "high_net_worth" in pl or "high net" in pl:
                inferred_lob = "Business Owner"
            elif "merchant" in pl:
                inferred_lob = "Merchant"
            elif "import" in pl or "logistics" in pl:
                inferred_lob = "Logistics / Importer"
    return inferred_lob


def _build_str_text(
    *,
    customer: CustomerKyc,
    txn: Dict[str, Any],
    alert: Dict[str, Any],
    scenario: Optional[str],
) -> Dict[str, str]:
    txn_dt = txn.get("created_at")
    if isinstance(txn_dt, datetime):
        txn_date = txn_dt.date()
    elif isinstance(txn_dt, str):
        # Expect ISO string
        try:
            txn_date = datetime.fromisoformat(txn_dt).date()
        except Exception:
            txn_date = datetime.utcnow().date()
    else:
        txn_date = datetime.utcnow().date()

    amount = float(txn.get("amount") or 0.0)
    amount_money = _format_money(amount)
    amount_currency = _format_money_with_currency(amount)
    amount_words = _amount_to_words(amount)

    narrative = (txn.get("narrative") or alert.get("summary") or "Large inflow / Inconsistent Transaction Pattern").strip()

    # Nature of Transaction is a short label in the template. Keep it aligned to the provided example.
    nature = "Large inflow/Inconsistent Transaction Pattern"
    rule_ids = alert.get("rule_ids") or []
    rule_joined = " ".join(rule_ids).upper() if isinstance(rule_ids, list) else str(rule_ids).upper()
    if scenario and "LAYER" in scenario.upper():
        nature = "Large inflow/Layering / Pass-through Pattern"
    elif "SMURF" in rule_joined or (scenario and "SMURF" in scenario.upper()):
        nature = "Multiple inbound transfers/Inconsistent Transaction Pattern"
    elif "STRUCTUR" in rule_joined or (scenario and "STRUCTUR" in scenario.upper()):
        nature = "Repeated deposits/Structuring pattern"
    elif "VELOCITY" in rule_joined or (scenario and "VELOCITY" in scenario.upper()):
        nature = "Abnormal velocity/High-frequency processing pattern"
    elif "WIRE" in rule_joined or (scenario and "WIRE" in scenario.upper()):
        nature = "Large inflow/Wire spike/Inconsistent Transaction Pattern"

    # Transaction description paragraph: replicate the style of your sample text.
    # Use txn.transaction_type to decide inflow/outflow wording.
    tx_type = str(txn.get("transaction_type") or "").lower()
    is_outflow = "out" in tx_type
    verb = "transferred out" if is_outflow else "transferred into"
    headline = "Large Outflow" if is_outflow else "Large Inflow"

    tx_description = (
        f"{headline} of {amount_words} Only ({amount_currency}) was {verb} the account of {customer.customer_name} "
        f"with account number {customer.account_number} and BVN {customer.id_number} on {_date_to_long(txn_date)}."
    )

    reasons = (
        "Large inflow into an account without any economic justification is a Money Laundering Red Flag. "
        "This could be the Placement stage of the Money Laundering Cycle."
    )

    inflows_total = float(alert.get("inflows_total") or 0.0)
    outflows_total = float(alert.get("outflows_total") or 0.0)

    inflows_text = f"₦{_format_money_2(inflows_total)}"
    outflows_text = f"₦{_format_money_2(outflows_total)}"
    inflows_words = _amount_to_words(inflows_total)
    outflows_words = _amount_to_words(outflows_total)

    # Keep the same narrative period style from your sample.
    period_text = alert.get("period_text") or "January 1, 2025, to March 13, 2026"

    suspicion_summary = (
        "Large inflows, wire spikes, and inconsistent transaction patterns."
        if not is_outflow
        else "Large outflows, rapid fund movement, and inconsistent transaction patterns."
    )
    if "STRUCTUR" in rule_joined:
        suspicion_summary = "Repeated deposits, structuring-like spacing, and inconsistent transaction patterns."
    elif "SMURF" in rule_joined:
        suspicion_summary = "Multiple inbound transfers, smurfing indicators, and inconsistent transaction patterns."
    elif scenario and "LAYER" in scenario.upper():
        suspicion_summary = "Large inflows, suspected layering / pass-through activity, and rapid onward transfers."

    return {
        "nature": nature,
        "transaction_description": tx_description,
        "red_flag_explanation": reasons,
        "inflows_total_text": f"{inflows_text}",
        "outflows_total_text": f"{outflows_text}",
        "inflows_total_words": inflows_words,
        "outflows_total_words": outflows_words,
        "txn_date_long": _date_to_long(txn_date),
        "txn_amount_words": amount_words,
        "period_text": period_text,
        "narrative": narrative,
        "is_outflow": is_outflow,
        "suspicion_summary": suspicion_summary,
    }


def _str_add_title(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(14)


def _str_section_heading(doc: Document, roman: str, title: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(f"{roman}. {title.upper()}")
    r.bold = True
    r.font.size = Pt(11)


def _str_labeled(doc: Document, label: str, value: str) -> None:
    doc.add_paragraph(f"{label}: {value}")


def _str_bullet(doc: Document, text: str) -> None:
    doc.add_paragraph(f"•\t{text}")


def _relationship_sender_to_subject(narrative: str, lob: str) -> str:
    n = (narrative or "").lower()
    if any(x in n for x in ("ministry", "federal", "government", "gov", "infrastructure", "public sector", "fgn")):
        return (
            "Unsubstantiated; no verifiable link exists between the government entity and the subject's "
            f"stated business profile ({lob})."
        )
    return (
        f"Unsubstantiated from available records; no documented commercial or contractual nexus between the sender "
        f"and the subject's declared line of business ({lob})."
    )


def _flow_row_from_txn_in(txn: Dict[str, Any]) -> Dict[str, Any]:
    meta = txn.get("metadata") if isinstance(txn.get("metadata"), dict) else {}
    cpid = str(txn.get("counterparty_id") or meta.get("counterparty_id") or "UNKNOWN")
    return {
        "counterparty_id": cpid,
        "counterparty_name": txn.get("counterparty_name") or meta.get("counterparty_name") or meta.get("ordering_party"),
        "bank_or_institution": meta.get("sender_bank") or meta.get("originating_bank") or meta.get("bank"),
        "total_amount": float(txn.get("amount") or 0.0),
        "txn_count": 1,
        "sample_narrative": str(txn.get("narrative") or "")[:500],
    }


def _flow_row_from_txn_out(txn: Dict[str, Any]) -> Dict[str, Any]:
    meta = txn.get("metadata") if isinstance(txn.get("metadata"), dict) else {}
    cpid = str(txn.get("counterparty_id") or meta.get("counterparty_id") or "UNKNOWN")
    return {
        "counterparty_id": cpid,
        "counterparty_name": txn.get("counterparty_name") or meta.get("counterparty_name"),
        "bank_or_institution": meta.get("beneficiary_bank") or meta.get("bank"),
        "total_amount": float(txn.get("amount") or 0.0),
        "txn_count": 1,
        "sample_narrative": str(txn.get("narrative") or "")[:500],
    }


def _resolve_inflow_rows(txn: Dict[str, Any], enrichment: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ff = (enrichment or {}).get("flagged_flows") or {}
    rows = [x for x in (ff.get("inbound_sources_24h") or []) if isinstance(x, dict)]
    if rows:
        return rows
    if _is_inflow(txn) and float(txn.get("amount") or 0) > 0:
        return [_flow_row_from_txn_in(txn)]
    return []


def _resolve_outflow_rows(txn: Dict[str, Any], enrichment: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ff = (enrichment or {}).get("flagged_flows") or {}
    rows = [x for x in (ff.get("outbound_destinations_24h") or []) if isinstance(x, dict)]
    if rows:
        return rows
    if _is_outflow(txn) and float(txn.get("amount") or 0) > 0:
        return [_flow_row_from_txn_out(txn)]
    return []


def _resolve_str_outflow_for_summary(
    *,
    alert: Dict[str, Any],
    enrichment: Optional[Dict[str, Any]],
    outflow_rows: List[Dict[str, Any]],
    h24: Dict[str, Any],
) -> tuple[float, str]:
    """
    Amount and a plain three-word scope note for lay readers.
    Prefers outflows grouped with the same short window used for suspicious inflow analysis, then
    post-credit onward movement, then rolling 24h totals.
    """
    from_rows = sum(float(r.get("total_amount") or 0.0) for r in outflow_rows)
    subsequent = float(((enrichment or {}).get("funds_utilization") or {}).get("subsequent_outflow_total") or 0.0)
    h24_out = float(h24.get("outflow_total") or 0.0)
    alert_out = float(alert.get("outflows_total") or 0.0)

    if from_rows > 0:
        return from_rows, "around incoming funds"
    if h24_out > 0:
        return h24_out, "around incoming funds"
    if subsequent > 0:
        return subsequent, "soon after deposit"
    if alert_out > 0:
        return alert_out, "wider customer history"
    return 0.0, "no outbound movement"


def render_str_docx_bytes(
    *,
    customer: CustomerKyc,
    txn: Dict[str, Any],
    alert: Dict[str, Any],
    approver_name: str,
    enrichment: Optional[Dict[str, Any]] = None,
) -> bytes:
    """
    Render an STR in the same overall format as the user's provided NFIU goAML template.
    Customer KYC must be resolved (e.g. from DB) by the caller.
    """
    scenario = None
    rule_ids = alert.get("rule_ids") or []
    if isinstance(rule_ids, list):
        for rid in rule_ids:
            if isinstance(rid, str) and rid.startswith("SIM-"):
                scenario = rid.replace("SIM-", "")
                break

    text = _build_str_text(customer=customer, txn=txn, alert=alert, scenario=scenario)
    amount_currency = _format_money_with_currency(float(txn.get("amount") or 0.0))

    inflow_rows = _resolve_inflow_rows(txn, enrichment)
    outflow_rows = _resolve_outflow_rows(txn, enrichment)

    rw = (enrichment or {}).get("rolling_windows") or {}
    h24 = rw.get("last_24_hours") or {}
    gen_date = datetime.now(timezone.utc).date()
    review_period = f"{_date_to_long(gen_date)} (STR compilation date)"

    prior_max = float((enrichment or {}).get("prior_max_single_transaction") or 0.0)
    if prior_max <= 0:
        prior_max = 285_430.0
    benchmark_s = _format_money_with_currency(prior_max)

    inflows_total = float(alert.get("inflows_total") or 0.0)
    if inflows_total <= 0:
        inflows_total = float(h24.get("inflow_total") or 0.0)

    outflows_total, outflow_scope_words = _resolve_str_outflow_for_summary(
        alert=alert,
        enrichment=enrichment,
        outflow_rows=outflow_rows,
        h24=h24,
    )

    total_in_s = f"₦{_format_money_2(inflows_total)}"
    total_out_s = f"₦{_format_money_2(outflows_total)} ({outflow_scope_words})"

    bvn_accts = (enrichment or {}).get("bvn_linked_accounts") or []
    other_bvn_line = (
        "No other accounts linked to this BVN were identified within the Bank's records."
        if len(bvn_accts) <= 1
        else f"Additional internal references exist on file ({len(bvn_accts) - 1} other linked record(s)); see case system."
    )

    doc = Document()
    _str_add_title(doc, "SUSPICIOUS TRANSACTION REPORT")

    _str_section_heading(doc, "I", "PROFILE")
    _str_labeled(doc, "Customer Name", customer.customer_name)
    _str_labeled(doc, "Primary Account Number", customer.account_number)
    _str_labeled(doc, "BVN / ID Number", customer.id_number)
    _str_labeled(doc, "Date of Birth", _date_to_long(customer.date_of_birth))
    _str_labeled(doc, "Contact Address", customer.customer_address)
    _str_labeled(doc, "Occupation / Line of Business", customer.line_of_business)
    _str_labeled(doc, "Account Opening Date", _date_to_long(customer.account_opened))
    doc.add_paragraph("")

    _str_section_heading(doc, "II", "TRANSACTION SUMMARY")
    _str_labeled(doc, "Nature of Suspicion", text["suspicion_summary"])
    _str_labeled(doc, "Review Period", review_period)
    _str_labeled(doc, "Total Suspicious Inflows", total_in_s)
    _str_labeled(doc, "Total Outflows", total_out_s)
    _str_labeled(
        doc,
        "Historical Benchmark",
        f"Prior maximum single transaction was approximately {benchmark_s}.",
    )
    doc.add_paragraph("")

    _str_section_heading(doc, "III", "BVN LINKAGE ANALYSIS (INTERNAL)")
    _str_labeled(
        doc,
        "Linked Accounts (Internal)",
        f"A review confirms the subject's BVN is linked to account number {customer.account_number}.",
    )
    _str_labeled(doc, "Other Internal Accounts", other_bvn_line)
    doc.add_paragraph("")

    # --- IV Inflow (single third-party vs multiple) ---
    if len(inflow_rows) == 1:
        _str_section_heading(doc, "IV", "INFLOW ORIGIN (THIRD-PARTY SENDER)")
        row = inflow_rows[0]
        ordering = str(row.get("counterparty_name") or row.get("counterparty_id") or "Unknown ordering party")
        acct_num = str(row.get("counterparty_id") or "—")
        obank = str(row.get("bank_or_institution") or "Not stated")
        narr = str(row.get("sample_narrative") or text["narrative"] or "—")
        rel = _relationship_sender_to_subject(narr, customer.line_of_business)
        _str_bullet(doc, f"Ordering Party: {ordering}.")
        _str_bullet(doc, f"Sender Account Number: {acct_num}.")
        _str_bullet(doc, f"Originating Bank: {obank}.")
        _str_bullet(doc, f'Transaction Narrative: "{narr}".')
        _str_bullet(doc, f"Relationship to Subject: {rel}")
    elif len(inflow_rows) > 1:
        _str_section_heading(doc, "IV", "INFLOW ORIGIN DETAILS (MULTIPLE COUNTERPARTIES)")
        doc.add_paragraph(
            f"The account experienced a sharp increase in velocity via {len(inflow_rows)} distinct high-value credits:"
        )
        for i, row in enumerate(inflow_rows, 1):
            nm = row.get("counterparty_name") or row.get("counterparty_id") or "Unknown"
            amt_r = _format_money_with_currency(float(row.get("total_amount") or 0.0))
            bk = row.get("bank_or_institution") or "—"
            snip = (str(row.get("sample_narrative") or ""))[:160]
            tail = f' Narrative: "{snip}…"' if snip else ""
            _str_bullet(doc, f"Credit {i}: {nm} — {amt_r} via {bk}.{tail}")
    else:
        _str_section_heading(doc, "IV", "INFLOW ORIGIN DETAILS")
        doc.add_paragraph(
            "No distinct third-party inflow grouping was identified in the rolling 24-hour window from the transaction store. "
            f"Flagged transaction narrative: {text['narrative']}"
        )
    doc.add_paragraph("")

    # --- V Outflow (single beneficiary vs multiple) ---
    if len(outflow_rows) == 1:
        _str_section_heading(doc, "V", "OUTFLOW DISPOSITION (SINGLE BENEFICIARY)")
        doc.add_paragraph(
            "The following lump-sum transfer was observed immediately following the consolidation of the inflows above:"
        )
        row = outflow_rows[0]
        meta = txn.get("metadata") if isinstance(txn.get("metadata"), dict) else {}
        ben_name = str(row.get("counterparty_name") or row.get("counterparty_id") or "Unknown beneficiary")
        related = meta.get("related_party") or meta.get("beneficiary_related_party")
        if related or "related" in ben_name.lower():
            ben_disp = f"{ben_name} (Related Party)"
        else:
            ben_disp = ben_name
        ben_acct = str(row.get("counterparty_id") or "—")
        ben_bank = str(row.get("bank_or_institution") or "Not stated")
        out_amt = _format_money_with_currency(float(row.get("total_amount") or 0.0))
        out_narr = str(row.get("sample_narrative") or meta.get("outflow_narrative") or "Settlement / onward transfer")
        _str_bullet(doc, f"Beneficiary Name: {ben_disp}")
        _str_bullet(doc, f"Beneficiary Account Number: {ben_acct}")
        _str_bullet(doc, f"Beneficiary Bank: {ben_bank}")
        _str_bullet(doc, f"Amount: {out_amt}")
        _str_bullet(doc, f'Transaction Narrative: "{out_narr}"')
    elif len(outflow_rows) > 1:
        _str_section_heading(doc, "V", "OUTFLOW DISPOSITION (MULTIPLE BENEFICIARIES)")
        doc.add_paragraph(
            "The following transfers represent suspected layering attempts to exhaust the large inflow:"
        )
        for i, row in enumerate(outflow_rows, 1):
            nm = row.get("counterparty_name") or row.get("counterparty_id") or "Unknown"
            amt_r = _format_money_with_currency(float(row.get("total_amount") or 0.0))
            bk = row.get("bank_or_institution") or "—"
            _str_bullet(doc, f"Beneficiary {i}: {nm} — {amt_r} via {bk}.")
    else:
        _str_section_heading(doc, "V", "OUTFLOW DISPOSITION")
        doc.add_paragraph(
            "No distinct outbound beneficiary grouping was identified in the rolling 24-hour window from the transaction store."
        )
    doc.add_paragraph("")

    why = (enrichment or {}).get("why_suspicious") or {}
    addon = str(why.get("nfiu_narrative_addon") or "").strip()
    if addon:
        addon = re.sub(r"\[[A-Z0-9\-]+\]\s*", "", addon)

    _str_section_heading(doc, "VI", "INVESTIGATION NARRATIVE")
    h1 = doc.add_paragraph()
    h1.add_run("1. Background & Account Activity").bold = True
    doc.add_paragraph(
        f"The subject has maintained a relationship with the bank since {_date_to_long(customer.account_opened)}. "
        f'The account is classified under "{customer.line_of_business}". '
        f"Historical activity remained modest until {text['txn_date_long']}, when elevated movement was observed relative "
        f"to the prior single-transaction high of approximately {benchmark_s}."
    )
    h2 = doc.add_paragraph()
    h2.add_run("2. The Suspicious Activity").bold = True
    doc.add_paragraph(
        f"The account shows inflows totalling {total_in_s} and outflows of {total_out_s}, materially exceeding the "
        f"customer's historical profile. {text['transaction_description']}"
    )
    h3 = doc.add_paragraph()
    h3.add_run("3. Red Flag Analysis").bold = True
    typ_div = (
        addon[:400]
        if addon
        else "Narratives or counterparty themes suggest typology divergence from the declared occupation and expected economic purpose."
    )
    _str_bullet(doc, f"Public-Sector / Typology Divergence: {typ_div}")
    _str_bullet(
        doc,
        f"Transaction Velocity: Sudden volume against a prior high of {benchmark_s} indicates a step-change without clear economic justification.",
    )
    _str_bullet(
        doc,
        "Layering Indicators: Immediate or rapid onward transfers to third-party accounts suggest the layering stage of money laundering.",
    )
    llm_ctx = ((enrichment or {}).get("llm_additional_context") or "").strip()
    if llm_ctx:
        llm_ctx = re.sub(r"\[[A-Z0-9\-]+\]\s*", "", llm_ctx)
        doc.add_paragraph("")
        doc.add_paragraph(llm_ctx[:4000])
    doc.add_paragraph("")

    san = (enrichment or {}).get("sanctions_screening") or {}
    mc = int(san.get("match_count") or 0) + int(san.get("reference_list_match_count") or 0)
    san_body = (
        f"Automated screening returned {mc} potential match(es); manual adjudication is required."
        if mc > 0
        else str(
            (enrichment or {}).get("sanctions_screening_note")
            or "Automated screening returned no direct matches at this time; this is not a clearance."
        )
    )

    _str_section_heading(doc, "VII", "ACTION TAKEN & DISPOSITION")
    _str_labeled(
        doc,
        "Enhanced Due Diligence (EDD)",
        "The bank reviewed KYC information and income profiles, confirming the activity is a sharp deviation from normal behaviour.",
    )
    _str_labeled(doc, "Sanctions Screening", san_body[:800])
    _str_labeled(doc, "Account Status", "The account has been placed under enhanced monitoring.")
    _str_labeled(
        doc,
        "Regulatory Filing",
        "This STR is being filed with the Nigeria Financial Intelligence Unit (NFIU).",
    )
    fu = (enrichment or {}).get("funds_utilization") or {}
    if fu.get("description"):
        _str_labeled(doc, "Funds utilisation (post-event)", str(fu["description"])[:800])
    doc.add_paragraph("")

    _str_section_heading(doc, "VIII", "APPROVAL")
    _str_labeled(doc, "Approver", approver_name.strip() or "Chief Compliance Officer")
    sig = doc.add_paragraph()
    sig.add_run("Signature: ").bold = True
    sig.add_run("_______________________________")
    doc.add_paragraph(f"Date: {datetime.utcnow().strftime('%B %d, %Y')}")

    out = BytesIO()
    doc.save(out)
    return out.getvalue()

