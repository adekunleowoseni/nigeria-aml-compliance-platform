from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, date
from io import BytesIO
from typing import Any, Dict, Optional

from docx import Document


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
    # Supports 0..999,999,999,999 (up to billions) which is enough for demo STR values.
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

    return CustomerKyc(
        customer_name=customer_name,
        account_number=account_number,
        account_opened=account_opened,
        customer_address=customer_address,
        line_of_business=line_of_business,
        phone_number=phone_number,
        date_of_birth=dob,
        id_number=bvn,
    )


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
    }


def render_str_docx_bytes(
    *,
    customer_id: str,
    txn: Dict[str, Any],
    alert: Dict[str, Any],
) -> bytes:
    """
    Render an STR in the same overall format as the user's provided NFIU goAML template.
    """
    scenario = None
    rule_ids = alert.get("rule_ids") or []
    if isinstance(rule_ids, list):
        for rid in rule_ids:
            if isinstance(rid, str) and rid.startswith("SIM-"):
                scenario = rid.replace("SIM-", "")
                break

    inferred_lob: Optional[str] = None
    meta = txn.get("metadata") or {}
    if isinstance(meta, dict):
        profile_label = meta.get("profile") or meta.get("pattern")
        if profile_label:
            # Map known simulation metadata patterns to an AML-friendly LOB label.
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

    customer = build_customer_kyc(customer_id, inferred_lob=inferred_lob, use_placeholders=True)
    text = _build_str_text(customer=customer, txn=txn, alert=alert, scenario=scenario)
    amount_currency = _format_money_with_currency(float(txn.get("amount") or 0.0))

    doc = Document()
    # Title
    title = doc.add_paragraph()
    run = title.add_run("SUSPICIOUS TRANSACTION REPORT")
    run.bold = True

    doc.add_paragraph(f"Customer Name: {customer.customer_name}")
    doc.add_paragraph(f"Customer Account Number: {customer.account_number}")
    doc.add_paragraph(f"Account Opened: {_date_to_long(customer.account_opened)}")
    doc.add_paragraph(f"Customer Address: {customer.customer_address}")
    doc.add_paragraph(f"Line of Business: {customer.line_of_business}")
    doc.add_paragraph(f"Phone Number: {customer.phone_number}")
    doc.add_paragraph(f"Date of Birth: {_date_to_long(customer.date_of_birth)}")
    doc.add_paragraph(f"ID Number: {customer.id_number}")

    doc.add_paragraph(f"Nature of Transaction: {text['nature']}")
    doc.add_paragraph(f"Transaction Description: {text['transaction_description']}")
    doc.add_paragraph(text["red_flag_explanation"])

    doc.add_paragraph(
        "The Customer commenced banking relationship with Guaranty Trust Bank Limited on "
        f"{customer.account_opened.strftime('%B %d, %Y')}."
    )
    doc.add_paragraph(
        f"The account was opened at the Asero Branch of the Bank in Ogun State, with account number {customer.account_number} "
        f"and BVN {customer.id_number}."
    )
    doc.add_paragraph(
        f"A review of the Bank's database reveals that the Customer's BVN is linked to account number {customer.account_number} in the Bank."
    )

    # Main narrative paragraph for the STR body (matches your template structure).
    is_outflow = text["transaction_description"].lower().startswith("large outflow")
    transfer_verb = "out of" if is_outflow else "into"
    headline = "Large Outflow" if is_outflow else "Large Inflow"
    doc.add_paragraph(
        f"Further review of the account revealed that on {text['txn_date_long']}, "
        f"{headline} of {text['txn_amount_words']} Only ({amount_currency}) was transferred "
        f"{transfer_verb} the account of {customer.customer_name} with account number {customer.account_number}. "
        "The fund has not been utilised in the customer's account as of the period of filing this report."
    )

    # Totals / processing statement (template style)
    # We keep the period constant as in the provided sample to match the goAML narrative formatting.
    doc.add_paragraph(
        f"The Customer has received inflows totalling {text['inflows_total_words']} ({text['inflows_total_text']}), "
        f"and processed outflows of {text['outflows_total_words']} ({text['outflows_total_text']}) "
        f"in her account from {text['period_text']}."
    )

    doc.add_paragraph(f"CDD and KYC carried out on the Customer at the point of account opening classified the Customer as a {customer.line_of_business}.")

    doc.add_paragraph("We have concerns over this transaction based on the following:")
    doc.add_paragraph("1. Inconsistency with Known Occupation & Income Profile")
    doc.add_paragraph("2. Deviation from Customer's Transaction Behaviour")
    doc.add_paragraph("3. Lack of Clear Economic Purpose")
    doc.add_paragraph("4. Relationship with the Sender Cannot be Substantiated")

    doc.add_paragraph(
        "ACTION TAKEN: The Bank conducted an enhanced due diligence review on the customer and the transaction. "
        "The customer's KYC information, income profile, and historical transaction pattern were reviewed. "
        f"The {amount_currency} inflow/outflow was identified as inconsistent with the customer's known occupation and account behaviour. "
        "The account has been placed under enhanced monitoring. Relevant internal documentation was completed, "
        "and a Suspicious Transaction Report is being filed with the NFIU in accordance with AML/CFT obligations."
    )

    doc.add_paragraph("")
    doc.add_paragraph("APPROVAL")
    doc.add_paragraph("I have reviewed and confirmed that my comments have been incorporated. I am approving the filing of an STR/SAR with the NFIU.")
    doc.add_paragraph("APPROVER: _______________________________")
    doc.add_paragraph("XXXXXXXXXXXXXXXX")
    doc.add_paragraph(f"DATE: {datetime.utcnow().strftime('%B')} {datetime.utcnow().day}, {datetime.utcnow().year}")

    out = BytesIO()
    doc.save(out)
    return out.getvalue()

