"""
FTR (Funds Transfer Report) business rules: eligibility, filing deadline, XML/CSV rendering.

CBN publishes authoritative schema; this module provides a representative structure and sample alignment.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

# Normalized transaction_type values that qualify (case-insensitive match on normalized string).
_FTR_TYPES = frozenset(
    {
        "wire_transfer",
        "wire",
        "remittance",
        "intl_wire",
        "international_wire",
        "cross_border_transfer",
        "swift",
    }
)


def _norm_type(transaction_type: str) -> str:
    s = (transaction_type or "").strip().lower().replace(" ", "_").replace("-", "_")
    if s in ("wiretransfer",):
        return "wire_transfer"
    return s


def transaction_type_eligible(transaction_type: str) -> bool:
    n = _norm_type(transaction_type)
    if n in _FTR_TYPES:
        return True
    return "wire" in n or "remit" in n


def amount_meets_threshold(
    *,
    amount: float,
    currency: str,
    threshold_ngn: float,
    threshold_usd: float,
    usd_ngn_rate: float,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Amount vs NGN / USD thresholds; optional metadata ftr_amount_ngn_equivalent for other CCY."""
    md = metadata if isinstance(metadata, dict) else {}
    eq = md.get("ftr_amount_ngn_equivalent")
    if eq is not None:
        try:
            return float(eq) >= threshold_ngn
        except (TypeError, ValueError):
            pass
    cur = (currency or "NGN").strip().upper()
    amt = float(amount or 0)
    if cur == "NGN":
        return amt >= threshold_ngn
    if cur == "USD":
        return amt >= threshold_usd
    rate = max(float(usd_ngn_rate or 0), 1e-9)
    if cur == "EUR":
        eur_usd = 1.08
        usd_amt = amt * eur_usd
        return usd_amt >= threshold_usd and (usd_amt * rate) >= threshold_ngn
    # Unknown CCY: compare to USD threshold only (institution should set ftr_amount_ngn_equivalent in metadata).
    return amt >= threshold_usd


def is_ftr_eligible(
    txn: Dict[str, Any],
    *,
    threshold_ngn: float,
    threshold_usd: float,
    usd_ngn_rate: float,
) -> Tuple[bool, str]:
    tt = str(txn.get("transaction_type") or "")
    if not transaction_type_eligible(tt):
        return False, "transaction_type_not_wire_or_remit"
    amt = float(txn.get("amount") or 0)
    cur = str(txn.get("currency") or "NGN")
    if not amount_meets_threshold(
        amount=amt,
        currency=cur,
        threshold_ngn=threshold_ngn,
        threshold_usd=threshold_usd,
        usd_ngn_rate=usd_ngn_rate,
        metadata=txn.get("metadata") if isinstance(txn.get("metadata"), dict) else None,
    ):
        return False, "below_threshold"
    return True, "ok"


def add_business_days(start: date, n: int) -> date:
    """Add n business days (Mon–Fri; no holiday calendar)."""
    d = start
    left = n
    step = 1
    while left > 0:
        d += timedelta(days=step)
        if d.weekday() < 5:
            left -= 1
    return d


def value_date_for_transaction(txn: Dict[str, Any]) -> date:
    md = txn.get("metadata") if isinstance(txn.get("metadata"), dict) else {}
    vd = md.get("value_date") or md.get("valueDate")
    if isinstance(vd, str) and len(vd) >= 10:
        try:
            return date.fromisoformat(vd[:10])
        except ValueError:
            pass
    ts = txn.get("created_at") or txn.get("timestamp")
    if isinstance(ts, datetime):
        return ts.date() if ts.tzinfo is None else ts.astimezone(timezone.utc).date()
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def filing_deadline_for_value_date(value_d: date) -> date:
    return add_business_days(value_d, 5)


def _el(parent: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e


def build_ftr_xml(row: Dict[str, Any], *, reporting_entity_name: str = "Reporting Institution") -> str:
    """
    Representative FTR XML (CBN-aligned field names; namespace placeholder — replace with official XSD).
    """
    root = ET.Element(
        "FundsTransferReport",
        {
            "xmlns": "urn:cbn-ng:ftr:sample-1.0",
            "version": "1.0",
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    _el(root, "ReportReference", row.get("report_ref") or "")
    _el(root, "ReportId", str(row.get("id") or ""))
    ent = ET.SubElement(root, "ReportingEntity")
    _el(ent, "Name", reporting_entity_name)

    tx = ET.SubElement(root, "Transfer")
    _el(tx, "TransactionId", str(row.get("transaction_id") or ""))
    _el(tx, "CustomerId", str(row.get("customer_id") or ""))
    _el(tx, "ValueDate", str(row.get("value_date") or ""))
    _el(tx, "FilingDeadline", str(row.get("filing_deadline") or ""))
    _el(tx, "Amount", str(row.get("amount") if row.get("amount") is not None else ""))
    _el(tx, "Currency", str(row.get("currency") or ""))
    _el(tx, "PaymentReference", str(row.get("payment_reference") or ""))
    _el(tx, "FilingStatus", str(row.get("filing_status") or ""))

    orig = ET.SubElement(tx, "Originator")
    _el(orig, "Name", row.get("originator_name") or "")
    _el(orig, "Account", row.get("originator_account") or "")
    _el(orig, "Address", row.get("originator_address") or "")
    _el(orig, "Country", row.get("originator_country") or "")

    ben = ET.SubElement(tx, "Beneficiary")
    _el(ben, "Name", row.get("beneficiary_name") or "")
    _el(ben, "Account", row.get("beneficiary_account") or "")
    _el(ben, "BankBIC", row.get("beneficiary_bank_bic") or "")
    _el(ben, "Country", row.get("beneficiary_country") or "")

    return ET.tostring(root, encoding="unicode", method="xml")


def build_ftr_csv(rows: List[Dict[str, Any]]) -> bytes:
    cols = [
        "report_ref",
        "transaction_id",
        "customer_id",
        "value_date",
        "filing_deadline",
        "amount",
        "currency",
        "originator_name",
        "originator_account",
        "beneficiary_name",
        "beneficiary_account",
        "beneficiary_bank_bic",
        "beneficiary_country",
        "filing_status",
        "payment_reference",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c) or "" for c in cols})
    return buf.getvalue().encode("utf-8")


def load_sample_template_xml() -> str:
    p = Path(__file__).resolve().parent.parent / "templates" / "ftr_template.xml"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!-- ftr_template.xml not found -->\n'


def map_transaction_to_party_fields(txn: Dict[str, Any], kyc: Any) -> Dict[str, Optional[str]]:
    """Derive originator from KYC model/dict and beneficiary from txn counterparty / metadata."""
    md = txn.get("metadata") if isinstance(txn.get("metadata"), dict) else {}

    def _kyc_attr(name: str) -> str:
        if kyc is None:
            return ""
        if isinstance(kyc, dict):
            return str(kyc.get(name) or "")
        return str(getattr(kyc, name, "") or "")

    originator_name = _kyc_attr("customer_name") or str(md.get("originator_name") or "")
    originator_account = _kyc_attr("account_number") or str(md.get("originator_account") or "")
    originator_address = _kyc_attr("customer_address") or str(md.get("originator_address") or "")
    originator_country = str(md.get("originator_country") or "NG")

    beneficiary_name = str(txn.get("counterparty_name") or md.get("beneficiary_name") or "")
    beneficiary_account = str(md.get("beneficiary_account") or txn.get("counterparty_id") or "")
    beneficiary_bank_bic = str(md.get("beneficiary_bank_bic") or md.get("bic") or "")
    beneficiary_country = str(md.get("beneficiary_country") or md.get("beneficiary_country_code") or "")

    payment_reference = str(md.get("payment_reference") or md.get("reference") or txn.get("id") or "")

    return {
        "originator_name": originator_name or None,
        "originator_account": originator_account or None,
        "originator_address": originator_address or None,
        "originator_country": originator_country or None,
        "beneficiary_name": beneficiary_name or None,
        "beneficiary_account": beneficiary_account or None,
        "beneficiary_bank_bic": beneficiary_bank_bic or None,
        "beneficiary_country": beneficiary_country or None,
        "payment_reference": payment_reference or None,
    }
