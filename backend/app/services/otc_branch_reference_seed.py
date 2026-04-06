"""
Reference dataset modelled on a branch OTC / STR intake spreadsheet (Apr 2026 sample).

**OTC ESTR alerts** (Alerts → “OTC / ESTR alerts”): only the **cash** rows — reference STR IDs **14320**, **14295**,
and **14318** (deposit above threshold ×2, USD cash withdrawal). Those alerts carry ``otc_report_kind=otc_estr`` and feed
Regulatory → OTC extended return (ESTR).

**OTC ESAR** (SAR path): the other seven rows (name / DOB / BVN-profile changes).

Call `POST /demo/seed-otc-branch-reference` to load into in-memory stores (+ optional Postgres KYC upsert).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List

from fastapi import Request

from app.api.v1.in_memory_stores import _ALERTS, _TXNS
from app.models.alert import AlertResponse, otc_report_kind_for_subject
from app.models.transaction import TransactionResponse
from app.services.customer_kyc_db import upsert_customer_kyc_explicit
from app.services.zone_branch import ensure_txn_aml_geo_metadata


def _parse_us_datetime(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%m/%d/%Y %I:%M %p")


# Columns: str_id, request_at (US), branch, account, customer_name, subject_detail, amount_note,
# amount (float), currency, reason, purpose, documents, otc_subject (API enum)
_OTC_BRANCH_ROWS: List[Dict[str, Any]] = [
    {
        "str_id": "14320",
        "request_at": "04/01/2026 5:44 PM",
        "branch": "ASABA 2",
        "account": "053350705787",
        "customer_name": "MUSA ABDULEEM",
        "subject_detail": "Deposit Above Threshold",
        "amount": 5_000_000.0,
        "currency": "NGN",
        "reason": "The cash deposit was too large hence it was splitted",
        "purpose": "Customer claim its for business purposes",
        "documents": "DEPOSIT SLIP",
        "otc_subject": "cash_deposit",
        "txn_type": "cash_deposit",
    },
    {
        "str_id": "14295",
        "request_at": "04/01/2026 10:33 AM",
        "branch": "BAUCHI",
        "account": "053350705787",
        "customer_name": "ALI AMD ALA",
        "subject_detail": "CASH WITHDRAWAL OF $20,000 ON 31-03-2026",
        "amount": 20_000.0,
        "currency": "USD",
        "reason": "HUGE CASH WITHDRAWAL",
        "purpose": "Customer claim its for business purposes",
        "documents": "DEPOSIT SLIP",
        "otc_subject": "cash_withdrawal",
        "txn_type": "cash_withdrawal",
    },
    {
        "str_id": "14299",
        "request_at": "04/01/2026 12:10 PM",
        "branch": "FESTAC 2",
        "account": "053350705787",
        "customer_name": "ROBERT LEE NAGBE",
        "subject_detail": "Partial NAME CORRECTION — from ROBERT LEE NAGBE to NAGBE ROBERT LEE",
        "amount": 0.0,
        "currency": "NGN",
        "reason": "CUSTOMER WANT HIS NAME TO BE THE SAME WITH NIN",
        "purpose": "CORRECTION OF NAME due to marriage bond",
        "documents": "AFFIDAVIT AND NEWS PAPER PUBLICATION",
        "otc_subject": "bvn_partial_name_change",
        "txn_type": "transfer_in",
    },
    {
        "str_id": "14305",
        "request_at": "04/01/2026 1:27 PM",
        "branch": "IKWERRE ROAD, PH6",
        "account": "053350705787",
        "customer_name": "ARUA GODSWILL PAN",
        "subject_detail": "complete name change — from ROBERT LEE NAGBE to ARUA GODSWILL PAN",
        "amount": 0.0,
        "currency": "NGN",
        "reason": "changes emanated from error made during BVN capturing",
        "purpose": "changes emanated from error made during BVN capturing",
        "documents": "AFFIDAVIT AND NEWS PAPER PUBLICATION",
        "otc_subject": "full_name_change",
        "txn_type": "transfer_in",
    },
    {
        "str_id": "14310",
        "request_at": "04/01/2026 11:41 AM",
        "branch": "KANO IV-BACHIRAWA ROAD",
        "account": "053350705787",
        "customer_name": "HAIMU NUHU",
        "subject_detail": "Date of birth update and partial name change — DOB (1980→1969); HAIMU NUHU HASHIMU → HAIMU NUHU",
        "amount": 0.0,
        "currency": "NGN",
        "reason": "changes emanated from error made during BVN capturing",
        "purpose": "changes emanated from error made during BVN capturing",
        "documents": "AFFIDAVIT, BIRTH CERTIFICATE, NIN DETAILS AND NEWS PAPER PUBLICATION",
        "otc_subject": "name_and_dob_update",
        "txn_type": "transfer_in",
    },
    {
        "str_id": "14302",
        "request_at": "04/01/2026 1:00 PM",
        "branch": "KANO IV-BACHIRAWA ROAD",
        "account": "053350705787",
        "customer_name": "AMU MAD LURNAU",
        "subject_detail": "PARTIAL NAME CHANGE — from MIKAYYU AHMAD to AHMAD LURWANU ADAMU",
        "amount": 0.0,
        "currency": "NGN",
        "reason": "CORRECTION OF NAME due to marriage bond",
        "purpose": "CORRECTION OF NAME due to marriage bond",
        "documents": "AFFIDAVIT, MARRIAGE CERT., NIN DETAILS, NEWS PAPER PUB.",
        "otc_subject": "bvn_partial_name_change",
        "txn_type": "transfer_in",
    },
    {
        "str_id": "14300",
        "request_at": "04/01/2026 12:19 PM",
        "branch": "SANGO OTTA",
        "account": "053350705787",
        "customer_name": "AU VICTIA HABAT",
        "subject_detail": "Date of birth update and partial name change — DOB (1980→1969); AU VICTIA HABAT → AUU VICTIA HARAT",
        "amount": 0.0,
        "currency": "NGN",
        "reason": "Changes emanated from misinformation from parents' records",
        "purpose": "Changes emanated from misinformation from parents' records",
        "documents": "AFFIDAVIT, NIN DETAILS, NEWS PAPER PUBLICATION",
        "otc_subject": "name_and_dob_update",
        "txn_type": "transfer_in",
    },
    {
        "str_id": "14318",
        "request_at": "04/01/2026 4:45 PM",
        "branch": "SANGO OTTA",
        "account": "053350705787",
        "customer_name": "ABDU AHI SADU",
        "subject_detail": "Deposit Above Threshold",
        "amount": 10_000_000.0,
        "currency": "NGN",
        "reason": "The cash deposit was too large hence it was structured",
        "purpose": "Customer claim its for business purposes",
        "documents": "DEPOSIT SLIP",
        "otc_subject": "cash_deposit",
        "txn_type": "cash_deposit",
    },
    {
        "str_id": "14308",
        "request_at": "04/01/2026 2:05 PM",
        "branch": "SHELL RESIDENTIAL AREA, PH 3",
        "account": "053350705787",
        "customer_name": "UDO MBEONG UDKA",
        "subject_detail": "Date of birth update and partial name change — DOB (1980→1969); UDO MBEONG UDKA → UDKAUDO MBETON",
        "amount": 0.0,
        "currency": "NGN",
        "reason": "changes emanated from error made during BVN capturing",
        "purpose": "changes emanated from error made during BVN capturing",
        "documents": "AFFIDAVIT, BIRTH CERTIFICATE, NIN DETAILS AND NEWS PAPER PUBLICATION",
        "otc_subject": "name_and_dob_update",
        "txn_type": "transfer_in",
    },
    {
        "str_id": "14294",
        "request_at": "04/01/2026 10:25 AM",
        "branch": "UYO",
        "account": "053350705787",
        "customer_name": "OFONG MIHAEL",
        "subject_detail": "Date of birth update — CUSTOMER WANTS TO CHANGE DOB FROM 1980 TO 1969 (11 YEARS)",
        "amount": 0.0,
        "currency": "NGN",
        "reason": "Customer wants details on BVN to be the same as NIN",
        "purpose": "Customer wants details on BVN to be the same as NIN",
        "documents": "AFFIDAVIT, BIRTH CERTIFICATE, NIN DETAILS AND NEWS PAPER PUBLICATION",
        "otc_subject": "dob_update",
        "txn_type": "transfer_in",
    },
]


def list_otc_branch_reference_rows() -> List[Dict[str, Any]]:
    """Return a shallow copy of the reference table (for APIs or exports)."""
    return [dict(r) for r in _OTC_BRANCH_ROWS]


def _bvn_for_row(str_id: str) -> str:
    base = int(str_id) % 1_000_000_000
    return f"22{base:09d}"


async def apply_otc_branch_reference_seed(
    request: Request,
    *,
    cco_pre_approve: bool = False,
) -> Dict[str, Any]:
    """
    Insert transactions + alerts for each spreadsheet row. Does not clear stores (caller clears if needed).

    By default, seeded rows have true-positive OTC on file but **no** CCO approval: use **Escalate** then **CCO review →
    Approve OTC** before Regulatory Reports lists them for ESTR/ESAR.

    Set ``cco_pre_approve=True`` to skip that (demo shortcut): ``cco_otc_approved`` and **escalated** status are set so
    report generation is immediately available.
    """
    pg = getattr(request.app.state, "pg", None)
    alert_ids: List[str] = []
    txn_ids: List[str] = []
    estr_ids: List[str] = []
    esar_ids: List[str] = []

    for row in _OTC_BRANCH_ROWS:
        sid = str(row["str_id"])
        cid = f"OTC-REF-{sid}"
        tid = f"TXN-OTC-{sid}"
        aid = f"ALERT-OTC-{sid}"
        created_at = _parse_us_datetime(row["request_at"])

        amt = float(row["amount"])
        if row["txn_type"] in ("cash_deposit", "cash_withdrawal") and amt <= 0:
            amt = 1.0
        if row["txn_type"] == "transfer_in" and amt <= 0:
            amt = 100.0  # token movement for non-cash OTC matters (demo)

        narrative = (
            f"{row['subject_detail']} | {row['reason']} | Purpose: {row['purpose']} | Docs: {row['documents']}"
        )[:900]

        md: Dict[str, Any] = {
            "walk_in": True,
            "channel": "otc_branch",
            "request_branch": row["branch"],
            "reference_str_id": sid,
            "documents_supplied": row["documents"],
            "branch_table_source": "spreadsheet_apr2026",
            "demo_skip_llm": True,
            "demo_severity": 0.88,
        }

        txn = TransactionResponse(
            id=tid,
            customer_id=cid,
            amount=amt,
            currency=str(row["currency"]),
            transaction_type=str(row["txn_type"]),
            narrative=narrative,
            counterparty_id=None,
            counterparty_name=f"OTC branch — {row['branch']}",
            status="posted",
            created_at=created_at,
            metadata=md,
        )
        txn.metadata = ensure_txn_aml_geo_metadata(txn.metadata, cid)
        _TXNS[tid] = txn

        subj = str(row["otc_subject"])
        kind = otc_report_kind_for_subject(subj)
        rationale = (
            f"Reason: {row['reason']}\n\nPurpose of transaction / request: {row['purpose']}\n\n"
            f"Documents supplied: {row['documents']}\n\nBranch: {row['branch']}"
        ).strip()

        now_hist = datetime.utcnow().isoformat() + "Z"
        hist: list[dict] = [
            {
                "action": "otc_report_seed",
                "reference_str_id": sid,
                "at": now_hist,
            }
        ]
        if cco_pre_approve:
            hist.append(
                {
                    "action": "seed_cco_pre_approve",
                    "note": "Demo shortcut: escalated + CCO OTC approval simulated for immediate report eligibility.",
                    "at": now_hist,
                }
            )

        alert = AlertResponse(
            id=aid,
            transaction_id=tid,
            customer_id=cid,
            severity=0.86,
            status="escalated" if cco_pre_approve else "open",
            rule_ids=["RULE-OTC-BRANCH-REF", f"REF-STR-{sid}"],
            summary=f"{row['subject_detail']} — {row['customer_name']} — {row['branch']}"[:500],
            otc_filing_reason="branch_referral",
            otc_filing_reason_detail=str(row["documents"])[:500],
            otc_outcome="true_positive",
            otc_subject=subj,
            otc_officer_rationale=rationale[:16000],
            otc_report_kind=kind,  # type: ignore[arg-type]
            cco_otc_approved=bool(cco_pre_approve),
            cco_estr_word_approved=False,
            otc_submitted_at=datetime.utcnow(),
            investigation_history=hist,
        )
        _ALERTS[aid] = alert
        txn.alert_id = aid
        _TXNS[tid] = txn

        await upsert_customer_kyc_explicit(
            pg,
            cid,
            customer_name=str(row["customer_name"]),
            account_number=str(row["account"]),
            account_opened=date(2019, 6, 1),
            customer_address=f"On file via branch referral — {row['branch']}",
            line_of_business="Not stated on branch intake (see OTC rationale)",
            phone_number=f"+234800{sid[-4:]}000",
            date_of_birth=date(1980, 1, 15),
            id_number=_bvn_for_row(sid),
        )

        alert_ids.append(aid)
        txn_ids.append(tid)
        if kind == "otc_estr":
            estr_ids.append(aid)
        else:
            esar_ids.append(aid)

    from app.services.demo_otc_kyc_documents_seed import seed_otc_branch_reference_kyc_documents

    kyc_docs = await seed_otc_branch_reference_kyc_documents(request, uploaded_by_email=None)

    return {
        "seed": "otc_branch_reference_apr2026",
        "rows": len(_OTC_BRANCH_ROWS),
        "alert_ids": alert_ids,
        "transaction_ids": txn_ids,
        "otc_estr_alert_ids": estr_ids,
        "otc_esar_alert_ids": esar_ids,
        "cco_pre_approved": cco_pre_approve,
        "kyc_documents_seed": kyc_docs,
        "note": (
            "Branch STR spreadsheet (Apr 2026): cash rows are OTC ESTR; profile/KYC rows are OTC ESAR. True-positive OTC "
            "unlocks Regulatory Reports without a CCO ESTR Word step."
        ),
    }


def summarize_row_for_export(row: Dict[str, Any]) -> Dict[str, Any]:
    """Structured view of one row (e.g. for JSON download)."""
    subj = str(row["otc_subject"])
    kind = otc_report_kind_for_subject(subj)
    return {
        "reference_str_id": row["str_id"],
        "request_branch": row["branch"],
        "account_number": row["account"],
        "customer_name": row["customer_name"],
        "subject": row["subject_detail"],
        "amount": row["amount"],
        "currency": row["currency"],
        "reason": row["reason"],
        "purpose": row["purpose"],
        "documents": row["documents"],
        "otc_subject": subj,
        "otc_report_kind": kind,
        "demo_customer_id": f"OTC-REF-{row['str_id']}",
        "demo_alert_id": f"ALERT-OTC-{row['str_id']}",
    }


def export_reference_table_json_ready() -> List[Dict[str, Any]]:
    return [summarize_row_for_export(r) for r in _OTC_BRANCH_ROWS]
