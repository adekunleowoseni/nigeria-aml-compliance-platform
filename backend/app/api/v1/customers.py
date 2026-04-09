"""Customer onboarding KYC, AOP generation, walk-in OTC transactions."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.api.v1.reports import _draft_aop_record, _latest_txn_for_customer, _report_download_content_disposition
from app.config import settings
from app.api.v1.transactions import _persist_txn_geo, _process_transaction_async
from app.core.security import get_current_user, require_admin
from app.models.transaction import TransactionResponse
from app.services import audit_trail
from app.services.aop_upload_db import (
    DOCUMENT_KIND_AOP_PACKAGE,
    VALID_DOCUMENT_KINDS,
    aop_upload_counts_for_customers,
    fetch_aop_upload_row,
    fetch_primary_aop_per_customer,
    insert_aop_upload_row,
    list_aop_uploads_from_db,
)
from app.services.aop_upload_store import (
    get_record,
    list_uploads_public,
    memory_upload_count,
    register_in_memory_catalog,
    write_aop_to_disk,
)
from app.services.compliance_bundle_narratives import build_aop_bundle_narrative
from app.services.customer_supporting_docs_pdf import (
    merge_customer_files_to_pdf,
    supporting_bundle_download_filename,
)
from app.services.customer_kyc_db import (
    fetch_customer_kyc_any,
    get_or_create_customer_kyc,
    list_customers_kyc,
    list_bvn_linked_accounts,
    upsert_customer_kyc_explicit,
)
from app.services.customer_risk_review_db import (
    add_review_cycle_with_rules,
    get_customer_review_rules,
    insert_review_alert_log,
    latest_review_for_customer,
    list_due_reviews,
    list_reviews_for_customer,
    normalize_risk_rating,
    upsert_customer_review_rules,
    upsert_customer_risk_review,
)
from app.services.mail_notify import send_plain_email
from app.services.regulatory_reports import regulatory_narrative_docx_bytes
from app.services.statement_of_account import (
    account_context_dates_for_customer,
    clamp_statement_period,
    format_statement_text,
    statement_lines_for_customer,
)
from app.services.str_word_generator import infer_line_of_business_from_customer_id

router = APIRouter(prefix="/customers", tags=["customers"])

_AOP_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
_AOP_UPLOAD_SUFFIXES = frozenset({".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"})


def _customer_has_demo_txn(customer_id: str) -> bool:
    from app.api.v1.in_memory_stores import _TXNS

    return any(t.customer_id == customer_id for t in _TXNS.values())


async def _resolve_customer_kyc(request: Request, customer_id: str) -> Any:
    pg = getattr(request.app.state, "pg", None)
    cid = customer_id.strip()
    kyc = await fetch_customer_kyc_any(pg, cid)
    if not kyc and _customer_has_demo_txn(cid):
        kyc = await get_or_create_customer_kyc(pg, cid, _txn_dict_for_customer(cid))
    return pg, cid, kyc


def _txn_dict_for_customer(customer_id: str) -> Dict[str, Any]:
    latest = _latest_txn_for_customer(customer_id)
    if latest:
        return latest.model_dump()
    return {
        "id": f"onboarding-{customer_id[:24]}",
        "customer_id": customer_id,
        "amount": 0.0,
        "currency": "NGN",
        "transaction_type": "onboarding",
        "narrative": "Customer profile / branch onboarding (no prior txn)",
        "metadata": {},
        "created_at": datetime.utcnow().isoformat(),
    }


class CustomerKycFields(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=500)
    account_number: str = Field(..., min_length=1, max_length=64)
    account_opened: date
    customer_address: str = Field(..., min_length=1, max_length=1000)
    line_of_business: str = Field(..., min_length=1, max_length=300)
    phone_number: str = Field(default="", max_length=64)
    date_of_birth: date
    id_number: str = Field(..., min_length=1, max_length=32, description="BVN / NIN")


class CustomerCreateBody(CustomerKycFields):
    customer_id: Optional[str] = Field(default=None, max_length=128)


class CustomerPatchBody(BaseModel):
    customer_name: Optional[str] = Field(default=None, max_length=500)
    account_number: Optional[str] = Field(default=None, max_length=64)
    account_opened: Optional[date] = None
    customer_address: Optional[str] = Field(default=None, max_length=1000)
    line_of_business: Optional[str] = Field(default=None, max_length=300)
    phone_number: Optional[str] = Field(default=None, max_length=64)
    date_of_birth: Optional[date] = None
    id_number: Optional[str] = Field(default=None, max_length=32)


class CustomerRiskReviewBody(BaseModel):
    last_review_date: date
    risk_rating: Literal["high", "medium", "low"]
    id_card_expiry_date: Optional[date] = None
    expected_turnover_match: bool = True
    expected_lodgement_match: bool = True
    expected_activity_match: bool = True
    pep_flag: bool = False
    account_update_within_period: bool = False
    management_approval_within_period: bool = False
    profile_changed: bool = False
    age_commensurate: bool = True
    activity_commensurate: bool = True
    recommendation: str = Field(default="", max_length=2000)
    send_edd_request: bool = False
    checklist: Dict[str, Any] = Field(default_factory=dict)


class CustomerRiskReviewAlertBody(BaseModel):
    customer_ids: List[str] = Field(default_factory=list)
    cco_email: Optional[str] = Field(default=None, max_length=320)
    relationship_manager_email: Optional[str] = Field(default=None, max_length=320)
    mode: Literal["individual", "bulk"] = "individual"


class CustomerRiskReviewAutoAllBody(BaseModel):
    only_due: bool = False
    limit: int = Field(default=5000, ge=1, le=20000)


class CustomerReviewRulesBody(BaseModel):
    high_months: int = Field(default=12, ge=1, le=120)
    medium_months: int = Field(default=18, ge=1, le=120)
    low_months: int = Field(default=36, ge=1, le=240)
    student_monthly_turnover_recommend_corporate_ngn: float = Field(default=10_000_000.0, ge=0)
    id_expiry_warning_days: int = Field(default=0, ge=0, le=3650)
    require_additional_docs_when_monthly_turnover_above_ngn: float = Field(default=20_000_000.0, ge=0)


class CustomerAopBody(BaseModel):
    account_product: str = Field(default="Savings", max_length=120)
    risk_rating: str = Field(default="medium", max_length=64)
    use_llm: bool = Field(
        default=True,
        description="If true, refine AOP narrative text (used in the account-opening PDF package) via configured LLM when available",
    )


class WalkInBody(BaseModel):
    direction: Literal["deposit", "withdrawal"]
    amount: float = Field(..., gt=0)
    currency: str = Field(default="NGN", max_length=8)
    narrative: Optional[str] = Field(default=None, max_length=2000)


def _kyc_to_api_dict(kyc: Any) -> Dict[str, Any]:
    return {
        "customer_name": kyc.customer_name,
        "account_number": kyc.account_number,
        "account_opened": kyc.account_opened.isoformat(),
        "customer_address": kyc.customer_address,
        "line_of_business": kyc.line_of_business,
        "phone_number": kyc.phone_number,
        "date_of_birth": kyc.date_of_birth.isoformat(),
        "id_number": kyc.id_number,
    }


def _actor_email(user: Dict[str, Any]) -> Optional[str]:
    e = user.get("email") or user.get("sub")
    if isinstance(e, str) and e.strip():
        return e.strip()[:320]
    return None


def _recent_customer_txn_stats(customer_id: str, days: int = 30) -> Dict[str, float]:
    from app.api.v1.in_memory_stores import _TXNS

    cutoff = datetime.utcnow() - timedelta(days=max(1, days))
    total = 0.0
    count = 0
    for t in _TXNS.values():
        if t.customer_id != customer_id:
            continue
        created = t.created_at if isinstance(t.created_at, datetime) else None
        if created and created < cutoff:
            continue
        total += float(getattr(t, "amount", 0.0) or 0.0)
        count += 1
    return {"amount_total": total, "count": float(count)}


def _derive_customer_risk_rating(kyc: Any, stats: Dict[str, float]) -> str:
    lob = str(getattr(kyc, "line_of_business", "") or "").lower()
    total = float(stats.get("amount_total") or 0.0)
    count = int(stats.get("count") or 0.0)
    base = "medium"
    if any(x in lob for x in ("student",)):
        base = "low"
    if any(x in lob for x in ("politician", "pep", "bureau", "casino", "crypto", "import", "logistics")):
        base = "high"
    if total >= 10_000_000 or count >= 80:
        if base == "low":
            return "medium"
        if base == "medium":
            return "high"
    if total >= 50_000_000:
        return "high"
    return base


def _auto_review_recommendations(
    *,
    line_of_business: str,
    account_holder_type: str,
    account_product: str,
    account_reference: Optional[str],
    has_aop_on_file: bool,
    monthly_turnover: float,
    latest_review: Optional[Dict[str, Any]],
    rules: Dict[str, Any],
) -> Dict[str, Any]:
    recs: List[str] = []
    needs_update = False
    lob_l = (line_of_business or "").strip().lower()
    student_threshold = float(rules.get("student_monthly_turnover_recommend_corporate_ngn") or 10_000_000.0)
    docs_threshold = float(rules.get("require_additional_docs_when_monthly_turnover_above_ngn") or 20_000_000.0)
    expiry_warn_days = int(rules.get("id_expiry_warning_days") or 0)

    if "student" in lob_l and monthly_turnover >= student_threshold:
        recs.append("Profile appears outdated for activity level. Recommend KYC update and consider corporate/current account migration.")
        needs_update = True
    if not has_aop_on_file:
        recs.append("AOP/supporting file not found. Recommend uploading current account opening package.")
        needs_update = True
    if monthly_turnover >= docs_threshold:
        recs.append("Monthly turnover is high. Recommend requesting additional supporting documents (EDD).")
        needs_update = True
    if account_holder_type == "individual" and account_product == "current" and not (account_reference or "").strip():
        recs.append("Current personal account missing reference. Recommend completing account reference details.")
        needs_update = True
    if latest_review:
        exp = latest_review.get("id_card_expiry_at")
        if hasattr(exp, "isoformat"):
            today = date.today()
            days_left = (exp - today).days
            if days_left < 0:
                recs.append("Customer ID is expired. Recommend immediate ID update.")
                needs_update = True
            elif days_left <= expiry_warn_days:
                recs.append(f"Customer ID expires in {days_left} day(s). Recommend renewal update.")
                needs_update = True
        for flag_name, text in (
            ("expected_turnover_match", "Declared turnover no longer matches activity. Recommend profile refresh."),
            ("expected_activity_match", "Declared expected activity no longer matches account behavior. Recommend profile refresh."),
            ("expected_lodgement_match", "Declared expected lodgement no longer matches deposits. Recommend profile refresh."),
        ):
            if latest_review.get(flag_name) is False:
                recs.append(text)
                needs_update = True
    return {"needs_profile_update": needs_update, "review_recommendations": recs}


def _line_of_business_for_customer(row_lob: Any, kyc: Any, customer_id: str) -> str:
    legacy_otc_placeholder = "not stated on branch intake (see otc rationale)"
    improved_otc_placeholder = "Occupation not provided during branch intake"
    lob = str(row_lob or "").strip()
    if lob:
        if lob.lower() == legacy_otc_placeholder:
            return improved_otc_placeholder
        return lob
    kyc_lob = str(getattr(kyc, "line_of_business", "") or "").strip()
    if kyc_lob:
        if kyc_lob.lower() == legacy_otc_placeholder:
            return improved_otc_placeholder
        return kyc_lob
    latest = _latest_txn_for_customer(customer_id)
    if latest and isinstance(latest.metadata, dict):
        md = latest.metadata
        for key in ("line_of_business", "occupation", "profile", "business_type"):
            v = str(md.get(key) or "").strip()
            if v:
                if v.lower() == legacy_otc_placeholder:
                    return improved_otc_placeholder
                return v
    inferred = str(infer_line_of_business_from_customer_id(customer_id) or "").strip()
    if inferred.lower() == legacy_otc_placeholder:
        return improved_otc_placeholder
    return inferred or "Line of business pending update"


def _stable_bucket(seed: str, mod: int) -> int:
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return int(h[:10], 16) % max(1, mod)


def _account_profile_for_customer(
    customer_id: str,
    customer_name: str,
    line_of_business: str,
    *,
    force_company: bool = False,
) -> Dict[str, Any]:
    name = (customer_name or "").strip()
    lob = (line_of_business or "").strip()
    company_markers = (" ltd", " limited", " plc", " inc", " company", " enterprise")
    looks_company = force_company or any(m in name.lower() for m in company_markers)
    if looks_company:
        company_name = name
        if not any(m in company_name.lower() for m in company_markers):
            company_name = f"{company_name} Holdings Ltd".strip()
        return {
            "customer_name": company_name,
            "account_holder_type": "corporate",
            "account_product": "current",
            "ledger_code": f"LED-CORP-{100 + _stable_bucket(customer_id, 900)}",
            "account_reference": None,
            "line_of_business": lob or "Corporate operations",
        }
    is_current = _stable_bucket(customer_id, 10) == 0
    return {
        "customer_name": name,
        "account_holder_type": "individual",
        "account_product": "current" if is_current else "savings",
        "ledger_code": f"LED-PERS-{100 + _stable_bucket(customer_id, 900)}",
        "account_reference": f"REF-{customer_id[-6:]}" if is_current else None,
        "line_of_business": lob or "Line of business pending update",
    }


async def _linked_companies_for_customer(pg: Any, cid: str, kyc: Any) -> List[Dict[str, Any]]:
    """Company accounts where this BVN is linked as director/shareholder (demo-safe inferred mapping)."""
    idn = str(getattr(kyc, "id_number", "") or "").strip()
    if not idn:
        return []
    rows, _ = await list_customers_kyc(pg, limit=5000, offset=0, q=None, merge_demo_sources=True)
    out: List[Dict[str, Any]] = []
    for r in rows:
        rid = str(r.get("customer_id") or "").strip()
        if not rid or rid == cid:
            continue
        id_match = str(r.get("id_number") or "").strip() == idn
        if not id_match:
            continue
        prof = _account_profile_for_customer(
            rid,
            str(r.get("customer_name") or ""),
            str(r.get("line_of_business") or ""),
            force_company=False,
        )
        if prof["account_holder_type"] != "corporate":
            continue
        role = "director" if _stable_bucket(f"{cid}:{rid}", 2) == 0 else "shareholder"
        out.append(
            {
                "company_customer_id": rid,
                "company_name": prof["customer_name"],
                "company_account_number": str(r.get("account_number") or ""),
                "relationship_role": role,
            }
        )
    if out:
        return out[:10]
    # Fallback demo relation where explicit linkage isn't captured yet.
    synthetic_name = f"{str(getattr(kyc, 'customer_name', '') or 'Customer').strip()} Group Ltd"
    return [
        {
            "company_customer_id": f"COMP-{cid[-6:]}",
            "company_name": synthetic_name,
            "company_account_number": f"{7000000000 + _stable_bucket(cid, 199999999):010d}",
            "relationship_role": "director",
        }
    ]


def _contact_email_for_customer(customer_id: str, customer_name: str) -> str:
    latest = _latest_txn_for_customer(customer_id)
    if latest and isinstance(latest.metadata, dict):
        md = latest.metadata
        for key in ("customer_email", "contact_email", "email"):
            v = str(md.get(key) or "").strip()
            if "@" in v:
                return v
    base = re.sub(r"[^a-z0-9._-]+", ".", (customer_name or customer_id).strip().lower())
    base = re.sub(r"\.+", ".", base).strip(".") or "customer"
    return f"{base[:48]}@example.com"


async def _merged_aop_uploads_for_api(pg: Any, customer_id: str) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    if pg is not None:
        try:
            db_rows = await list_aop_uploads_from_db(pg, customer_id)
            for r in db_rows:
                uid = str(r["upload_id"])
                seen.add(uid)
                out.append(
                    {
                        "upload_id": uid,
                        "filename": r["filename"],
                        "uploaded_at": r["uploaded_at"],
                        "size": int(r["size"]),
                        "persisted": True,
                        "document_kind": str(r.get("document_kind") or DOCUMENT_KIND_AOP_PACKAGE),
                    }
                )
        except Exception:
            pass
    for m in list_uploads_public(customer_id):
        uid = str(m["upload_id"])
        if uid not in seen:
            seen.add(uid)
            out.append(
                {
                    "upload_id": uid,
                    "filename": m["filename"],
                    "uploaded_at": m["uploaded_at"],
                    "size": int(m["size"]),
                    "persisted": bool(m.get("persisted", False)),
                    "document_kind": str(m.get("document_kind") or DOCUMENT_KIND_AOP_PACKAGE),
                }
            )
    out.sort(key=lambda x: str(x["uploaded_at"]), reverse=True)
    return out


async def _aop_download_path(pg: Any, customer_id: str, upload_id: str) -> Optional[Path]:
    if pg is not None:
        try:
            row = await fetch_aop_upload_row(pg, customer_id, upload_id)
            if row:
                p = row.get("_path")
                if p is not None and Path(p).is_file():
                    return Path(p)
        except Exception:
            pass
    rec = get_record(customer_id, upload_id)
    if rec and rec.get("_path"):
        p = Path(rec["_path"])
        if p.is_file():
            return p
    return None


@router.get("")
async def list_customers(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
):
    _ = user
    pg = getattr(request.app.state, "pg", None)
    review_rules = await get_customer_review_rules(pg)
    offset = (page - 1) * page_size
    merge_demo = settings.app_env == "development"
    rows, total = await list_customers_kyc(
        pg, limit=page_size, offset=offset, q=q, merge_demo_sources=merge_demo
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        ao = r.get("account_opened")
        out.append(
            {
                "customer_id": r["customer_id"],
                "customer_name": r["customer_name"],
                "account_number": r["account_number"],
                "account_opened": ao.isoformat() if hasattr(ao, "isoformat") else str(ao),
                "line_of_business": r.get("line_of_business"),
                "id_number": r.get("id_number"),
                "updated_at": r.get("updated_at").isoformat() if r.get("updated_at") else None,
            }
        )
    cids = [item["customer_id"] for item in out]
    db_counts: Dict[str, int] = {}
    if pg is not None and cids:
        try:
            db_counts = await aop_upload_counts_for_customers(pg, cids)
        except Exception:
            db_counts = {}
    primary_by_cid: Dict[str, Dict[str, str]] = {}
    if cids:
        try:
            primary_by_cid = await fetch_primary_aop_per_customer(pg, cids)
        except Exception:
            primary_by_cid = {}
    company_ids: set[str] = set()
    if cids:
        ranked = sorted(cids, key=lambda x: _stable_bucket(x, 10_000_000))
        company_ids = set(ranked[: min(30, len(ranked))])
    for item in out:
        cid = item["customer_id"]
        n_db = int(db_counts.get(cid, 0))
        n_mem = memory_upload_count(cid)
        item["aop_on_file"] = n_db > 0 or n_mem > 0
        item["aop_upload_count"] = n_db + n_mem
        prim = primary_by_cid.get(cid)
        if prim:
            item["primary_aop_upload_id"] = prim["upload_id"]
            item["primary_aop_filename"] = prim["filename"]
        kyc = await fetch_customer_kyc_any(pg, cid)
        item["line_of_business"] = _line_of_business_for_customer(item.get("line_of_business"), kyc, cid)
        prof = _account_profile_for_customer(
            cid,
            str(item.get("customer_name") or ""),
            str(item.get("line_of_business") or ""),
            force_company=cid in company_ids,
        )
        item["customer_name"] = prof["customer_name"]
        item["line_of_business"] = prof["line_of_business"]
        item["account_holder_type"] = prof["account_holder_type"]
        item["account_product"] = prof["account_product"]
        item["ledger_code"] = prof["ledger_code"]
        item["account_reference"] = prof["account_reference"]
        item["contact_email"] = _contact_email_for_customer(cid, str(item.get("customer_name") or cid))
        latest = await latest_review_for_customer(pg, cid)
        if latest:
            due = latest.get("next_review_due_at")
            item["risk_rating"] = str(latest.get("risk_rating") or "medium")
            item["last_review_date"] = latest.get("reviewed_at").isoformat() if hasattr(latest.get("reviewed_at"), "isoformat") else str(latest.get("reviewed_at") or "")
            item["next_review_due_at"] = due.isoformat() if hasattr(due, "isoformat") else str(due or "")
            item["review_status"] = "due" if (hasattr(due, "isoformat") and due <= date.today()) else "reviewed"
        elif kyc:
            inferred = _derive_customer_risk_rating(kyc, _recent_customer_txn_stats(cid, days=30))
            base_dt = getattr(kyc, "account_opened", None) or date.today()
            due = add_review_cycle_with_rules(base_dt, inferred, review_rules)
            item["risk_rating"] = inferred
            item["last_review_date"] = None
            item["next_review_due_at"] = due.isoformat()
            item["review_status"] = "due" if due <= date.today() else "pending"
        monthly_stats = _recent_customer_txn_stats(cid, days=30)
        latest_row = latest if latest else None
        rec = _auto_review_recommendations(
            line_of_business=str(item.get("line_of_business") or ""),
            account_holder_type=str(item.get("account_holder_type") or ""),
            account_product=str(item.get("account_product") or ""),
            account_reference=str(item.get("account_reference") or "") or None,
            has_aop_on_file=bool(item.get("aop_on_file")),
            monthly_turnover=float(monthly_stats.get("amount_total") or 0.0),
            latest_review=latest_row,
            rules=review_rules,
        )
        item["needs_profile_update"] = bool(rec["needs_profile_update"])
        item["review_recommendations"] = rec["review_recommendations"]
    return {"items": out, "total": total, "page": page, "page_size": page_size}


@router.get("/{customer_id}/statement/download")
async def download_customer_statement_of_account(
    request: Request,
    customer_id: str,
    period_start: Optional[date] = Query(None),
    period_end: Optional[date] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg, cid, kyc = await _resolve_customer_kyc(request, customer_id)
    if not kyc:
        raise HTTPException(status_code=404, detail="Customer not found")
    _ = user
    acc_start, _, opened_s = await account_context_dates_for_customer(pg, cid)
    today = datetime.utcnow().date()
    d_from, d_to = clamp_statement_period(acc_start, today, period_start, period_end)
    lines = statement_lines_for_customer(cid, d_from, d_to)
    text = format_statement_text(lines, cid, opened_s)
    doc_bytes = regulatory_narrative_docx_bytes(
        title="Statement of account",
        subtitle=f"Customer: {cid} · {d_from.isoformat()} → {d_to.isoformat()}",
        narrative=text,
        xml_excerpt=None,
        source_note="customer_statement",
    )
    customer_name = str(getattr(kyc, "customer_name", "") or "").strip() or cid
    return Response(
        content=doc_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": _report_download_content_disposition(customer_name, "SOA", "docx")},
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_customer(
    request: Request,
    body: CustomerCreateBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg = getattr(request.app.state, "pg", None)
    cid = (body.customer_id or "").strip()
    if not cid:
        cid = f"CUST-{uuid4().hex[:12].upper()}"
    if await fetch_customer_kyc_any(pg, cid):
        raise HTTPException(status_code=409, detail=f"customer_id already exists: {cid}")
    kyc = await upsert_customer_kyc_explicit(
        pg,
        cid,
        customer_name=body.customer_name,
        account_number=body.account_number,
        account_opened=body.account_opened,
        customer_address=body.customer_address,
        line_of_business=body.line_of_business,
        phone_number=body.phone_number or "—",
        date_of_birth=body.date_of_birth,
        id_number=body.id_number,
    )
    audit_trail.record_event_from_user(
        user,
        action="customer.kyc.created",
        resource_type="customer",
        resource_id=cid,
        details={"customer_name": kyc.customer_name, "account_number": kyc.account_number},
    )
    return {"customer_id": cid, "kyc": _kyc_to_api_dict(kyc)}


@router.get("/{customer_id}")
async def get_customer(
    request: Request,
    customer_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _ = user
    pg, cid, kyc = await _resolve_customer_kyc(request, customer_id)
    if not kyc:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {
        "customer_id": cid,
        "kyc": _kyc_to_api_dict(kyc),
        "aop_uploads": await _merged_aop_uploads_for_api(pg, cid),
        "risk_reviews": await list_reviews_for_customer(pg, cid, limit=10),
        "account_profile": _account_profile_for_customer(
            cid,
            str(getattr(kyc, "customer_name", "") or ""),
            str(getattr(kyc, "line_of_business", "") or ""),
        ),
        "linked_companies": await _linked_companies_for_customer(pg, cid, kyc),
    }


@router.get("/{customer_id}/related-accounts")
async def get_related_accounts(
    request: Request,
    customer_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _ = user
    pg, cid, kyc = await _resolve_customer_kyc(request, customer_id)
    if not kyc:
        raise HTTPException(status_code=404, detail="Customer not found")

    merge_demo = settings.app_env == "development"
    rows, _ = await list_customers_kyc(
        pg,
        limit=5000,
        offset=0,
        q=str(kyc.customer_name or "").strip(),
        merge_demo_sources=merge_demo,
    )
    base_name = str(kyc.customer_name or "").strip().lower()
    base_id_number = str(kyc.id_number or "").strip()

    by_id: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = str(r.get("customer_id") or "").strip()
        if not rid:
            continue
        nm = str(r.get("customer_name") or "").strip().lower()
        idn = str(r.get("id_number") or "").strip()
        # Prefer strict BVN/ID linkage. Fall back to exact-name match only when BVN is unavailable.
        same_person = (base_id_number and idn and idn == base_id_number) or (
            (not base_id_number) and nm and nm == base_name
        )
        if not same_person and rid != cid:
            continue
        prof = _account_profile_for_customer(
            rid,
            str(r.get("customer_name") or ""),
            str(r.get("line_of_business") or ""),
        )
        by_id[rid] = {
            "customer_id": rid,
            "customer_name": str(prof.get("customer_name") or r.get("customer_name") or ""),
            "account_number": str(r.get("account_number") or ""),
            "id_number": str(r.get("id_number") or "") or None,
            "updated_at": r.get("updated_at").isoformat() if r.get("updated_at") else None,
            "account_holder_type": str(prof.get("account_holder_type") or ""),
            "account_product": str(prof.get("account_product") or ""),
            "ledger_code": str(prof.get("ledger_code") or ""),
            "account_reference": str(prof.get("account_reference") or "") or None,
        }

    if cid not in by_id:
        prof = _account_profile_for_customer(
            cid,
            str(kyc.customer_name or ""),
            str(kyc.line_of_business or ""),
        )
        by_id[cid] = {
            "customer_id": cid,
            "customer_name": str(prof.get("customer_name") or kyc.customer_name or ""),
            "account_number": str(kyc.account_number or ""),
            "id_number": str(kyc.id_number or "") or None,
            "updated_at": None,
            "account_holder_type": str(prof.get("account_holder_type") or ""),
            "account_product": str(prof.get("account_product") or ""),
            "ledger_code": str(prof.get("ledger_code") or ""),
            "account_reference": str(prof.get("account_reference") or "") or None,
        }

    items = sorted(
        by_id.values(),
        key=lambda x: (0 if x["customer_id"] == cid else 1, str(x.get("account_number") or "")),
    )
    return {
        "primary_customer_id": cid,
        "customer_name": str(kyc.customer_name or ""),
        "total_accounts": len(items),
        "other_accounts": max(0, len(items) - 1),
        "items": items,
    }


@router.patch("/{customer_id}")
async def patch_customer(
    request: Request,
    customer_id: str,
    body: CustomerPatchBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg, cid, current = await _resolve_customer_kyc(request, customer_id)
    if not current:
        raise HTTPException(status_code=404, detail="Customer not found")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    merged = {
        "customer_name": data.get("customer_name", current.customer_name),
        "account_number": data.get("account_number", current.account_number),
        "account_opened": data.get("account_opened", current.account_opened),
        "customer_address": data.get("customer_address", current.customer_address),
        "line_of_business": data.get("line_of_business", current.line_of_business),
        "phone_number": data.get("phone_number", current.phone_number),
        "date_of_birth": data.get("date_of_birth", current.date_of_birth),
        "id_number": data.get("id_number", current.id_number),
    }
    kyc = await upsert_customer_kyc_explicit(pg, cid, **merged)
    audit_trail.record_event_from_user(
        user,
        action="customer.kyc.updated",
        resource_type="customer",
        resource_id=cid,
        details={"fields": list(data.keys())},
    )
    return {"customer_id": cid, "kyc": _kyc_to_api_dict(kyc)}


@router.post("/{customer_id}/risk-review")
async def submit_customer_risk_review(
    request: Request,
    customer_id: str,
    body: CustomerRiskReviewBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg, cid, kyc = await _resolve_customer_kyc(request, customer_id)
    if not kyc:
        raise HTTPException(status_code=404, detail="Customer not found")
    linked = await list_bvn_linked_accounts(pg, str(kyc.id_number or ""), primary_customer_id=cid)
    prev = await latest_review_for_customer(pg, cid)
    previous_rating = str(prev.get("risk_rating")) if prev else None
    stats = _recent_customer_txn_stats(cid, days=30)
    suggested = _derive_customer_risk_rating(kyc, stats)
    if body.pep_flag:
        suggested = "high"
    if not body.activity_commensurate or not body.expected_activity_match:
        suggested = "high" if suggested == "medium" else suggested
        if suggested == "low":
            suggested = "medium"
    if body.send_edd_request:
        suggested = "high"
    rules = await get_customer_review_rules(pg)
    next_due = add_review_cycle_with_rules(body.last_review_date, body.risk_rating, rules)
    review = await upsert_customer_risk_review(
        pg,
        {
            "customer_id": cid,
            "reviewed_at": body.last_review_date,
            "risk_rating": normalize_risk_rating(body.risk_rating),
            "previous_risk_rating": previous_rating,
            "next_review_due_at": next_due,
            "id_card_expiry_at": body.id_card_expiry_date,
            "bvn_linked_accounts_count": max(0, len(linked) - 1),
            "profile_changed": body.profile_changed,
            "account_update_within_period": body.account_update_within_period,
            "management_approval_within_period": body.management_approval_within_period,
            "age_commensurate": body.age_commensurate,
            "activity_commensurate": body.activity_commensurate,
            "pep_flag": body.pep_flag,
            "expected_turnover_match": body.expected_turnover_match,
            "expected_activity_match": body.expected_activity_match,
            "expected_lodgement_match": body.expected_lodgement_match,
            "suggested_risk_profile": suggested,
            "recommendation": body.recommendation,
            "status": "reviewed",
            "checklist_json": body.checklist,
        },
    )
    audit_trail.record_event_from_user(
        user,
        action="customer.risk_review.submitted",
        resource_type="customer",
        resource_id=cid,
        details={
            "review_id": review["review_id"],
            "risk_rating": review["risk_rating"],
            "suggested_risk_profile": suggested,
            "next_review_due_at": next_due.isoformat(),
            "send_edd_request": body.send_edd_request,
        },
    )
    return {"customer_id": cid, "review": review}


@router.get("/risk-reviews/due")
async def list_due_customer_reviews(
    request: Request,
    days_ahead: int = Query(0, ge=0, le=365),
    limit: int = Query(200, ge=1, le=2000),
    user: Dict[str, Any] = Depends(get_current_user),
):
    _ = user
    pg = getattr(request.app.state, "pg", None)
    rules = await get_customer_review_rules(pg)
    items = await list_due_reviews(pg, as_of=date.today(), days_ahead=days_ahead, limit=limit)
    # Also include customers without manual review records, using automatic schedule from risk profile.
    end_date = date.today() + timedelta(days=max(0, days_ahead))
    existing = {str(x.get("customer_id") or "") for x in items}
    rows, _ = await list_customers_kyc(pg, limit=limit, offset=0, q=None, merge_demo_sources=settings.app_env == "development")
    for r in rows:
        cid = str(r.get("customer_id") or "")
        if not cid or cid in existing:
            continue
        kyc = await fetch_customer_kyc_any(pg, cid)
        if not kyc:
            continue
        inferred = _derive_customer_risk_rating(kyc, _recent_customer_txn_stats(cid, days=30))
        opened = getattr(kyc, "account_opened", None) or date.today()
        due = add_review_cycle_with_rules(opened, inferred, rules)
        if due > end_date:
            continue
        items.append(
            {
                "review_id": None,
                "customer_id": cid,
                "risk_rating": inferred,
                "next_review_due_at": due,
                "reviewed_at": None,
                "customer_name": str(getattr(kyc, "customer_name", "") or ""),
                "account_number": str(getattr(kyc, "account_number", "") or ""),
                "id_number": str(getattr(kyc, "id_number", "") or ""),
                "auto_generated": True,
            }
        )
    for x in items:
        due = x.get("next_review_due_at")
        x["is_due"] = bool(hasattr(due, "isoformat") and due <= date.today())
    return {"items": items, "as_of": date.today().isoformat(), "days_ahead": days_ahead}


@router.post("/risk-reviews/alerts/send")
async def send_due_customer_review_alerts(
    request: Request,
    body: CustomerRiskReviewAlertBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg = getattr(request.app.state, "pg", None)
    targets = [c.strip() for c in body.customer_ids if c and c.strip()]
    if not targets:
        due = await list_due_reviews(pg, as_of=date.today(), days_ahead=0, limit=500)
        targets = [str(x.get("customer_id") or "") for x in due if str(x.get("customer_id") or "").strip()]
    sent: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for cid in targets:
        latest = await latest_review_for_customer(pg, cid)
        if not latest:
            continue
        due_date = latest.get("next_review_due_at")
        if not (hasattr(due_date, "isoformat") and due_date <= date.today()):
            continue
        recipients: List[tuple[str, str]] = []
        cco = (body.cco_email or settings.cco_email or "").strip()
        rm = (body.relationship_manager_email or "").strip()
        if cco:
            recipients.append((cco, "cco"))
        if rm:
            recipients.append((rm, "relationship_manager"))
        for email, role in recipients:
            subject = f"Customer risk review due - {cid}"
            msg = (
                f"Customer {cid} is due for periodic risk review.\n"
                f"Current risk rating: {latest.get('risk_rating')}\n"
                f"Due date: {due_date.isoformat() if hasattr(due_date, 'isoformat') else due_date}\n"
                f"Please complete review checks and update risk profile."
            )
            try:
                await send_plain_email([email], subject, msg)
                log_row = await insert_review_alert_log(
                    pg,
                    {
                        "customer_id": cid,
                        "review_id": latest.get("review_id"),
                        "due_date": due_date,
                        "recipient_email": email,
                        "recipient_role": role,
                        "mode": body.mode,
                        "status": "sent",
                        "detail": "risk-review due alert",
                    },
                )
                sent.append({"customer_id": cid, "recipient_email": email, "recipient_role": role, "log_id": log_row["id"]})
            except Exception as exc:
                failures.append({"customer_id": cid, "recipient_email": email, "error": str(exc)})
    audit_trail.record_event_from_user(
        user,
        action="customer.risk_review.alerts_sent",
        resource_type="customer",
        resource_id="bulk" if body.mode == "bulk" else (targets[0] if targets else "none"),
        details={"mode": body.mode, "sent": len(sent), "failed": len(failures)},
    )
    return {"status": "ok", "sent": sent, "failures": failures}


@router.post("/risk-reviews/review-all")
async def auto_review_all_customers(
    request: Request,
    body: CustomerRiskReviewAutoAllBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg = getattr(request.app.state, "pg", None)
    rules = await get_customer_review_rules(pg)
    rows, _ = await list_customers_kyc(
        pg,
        limit=int(body.limit),
        offset=0,
        q=None,
        merge_demo_sources=settings.app_env == "development",
    )
    processed = 0
    skipped = 0
    today = date.today()
    for r in rows:
        cid = str(r.get("customer_id") or "").strip()
        if not cid:
            continue
        kyc = await fetch_customer_kyc_any(pg, cid)
        if not kyc:
            skipped += 1
            continue
        inferred = _derive_customer_risk_rating(kyc, _recent_customer_txn_stats(cid, days=30))
        previous = await latest_review_for_customer(pg, cid)
        previous_rating = str(previous.get("risk_rating") or "") if previous else None
        last_date = today
        if body.only_due:
            due_at = previous.get("next_review_due_at") if previous else None
            if not (hasattr(due_at, "isoformat") and due_at <= today):
                skipped += 1
                continue
        next_due = add_review_cycle_with_rules(last_date, inferred, rules)
        recommendation = "Automatic periodic review generated from profile and recent activity."
        review = await upsert_customer_risk_review(
            pg,
            {
                "customer_id": cid,
                "reviewed_at": last_date,
                "risk_rating": normalize_risk_rating(inferred),
                "previous_risk_rating": previous_rating or None,
                "next_review_due_at": next_due,
                "id_card_expiry_at": None,
                "bvn_linked_accounts_count": 0,
                "profile_changed": False,
                "account_update_within_period": False,
                "management_approval_within_period": False,
                "age_commensurate": True,
                "activity_commensurate": True,
                "pep_flag": False,
                "expected_turnover_match": True,
                "expected_activity_match": True,
                "expected_lodgement_match": True,
                "suggested_risk_profile": inferred,
                "recommendation": recommendation,
                "status": "reviewed",
                "checklist_json": {
                    "auto_generated": True,
                    "source": "customers.risk-reviews.review-all",
                },
            },
        )
        _ = review
        processed += 1
    audit_trail.record_event_from_user(
        user,
        action="customer.risk_review.auto_review_all",
        resource_type="customer",
        resource_id="bulk",
        details={"processed": processed, "skipped": skipped, "only_due": bool(body.only_due), "limit": int(body.limit)},
    )
    return {"status": "ok", "processed": processed, "skipped": skipped, "only_due": bool(body.only_due)}


@router.get("/admin/review-rules")
async def get_admin_customer_review_rules(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    pg = getattr(request.app.state, "pg", None)
    rules = await get_customer_review_rules(pg)
    return {"rules": rules}


@router.put("/admin/review-rules")
async def put_admin_customer_review_rules(
    request: Request,
    body: CustomerReviewRulesBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    pg = getattr(request.app.state, "pg", None)
    rules = await upsert_customer_review_rules(
        pg,
        {
            "high_months": body.high_months,
            "medium_months": body.medium_months,
            "low_months": body.low_months,
            "student_monthly_turnover_recommend_corporate_ngn": body.student_monthly_turnover_recommend_corporate_ngn,
            "id_expiry_warning_days": body.id_expiry_warning_days,
            "require_additional_docs_when_monthly_turnover_above_ngn": body.require_additional_docs_when_monthly_turnover_above_ngn,
        },
    )
    audit_trail.record_event_from_user(
        user,
        action="admin.customer_review_rules.updated",
        resource_type="admin_setting",
        resource_id="customer_review_rules",
        details={"rules": rules},
    )
    return {"status": "ok", "rules": rules}


@router.post("/{customer_id}/aop/generate")
async def generate_customer_aop(
    request: Request,
    customer_id: str,
    body: CustomerAopBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg, cid, kyc = await _resolve_customer_kyc(request, customer_id)
    if not kyc:
        raise HTTPException(status_code=404, detail="Customer not found")
    txn_dict = _txn_dict_for_customer(cid)
    cust = await get_or_create_customer_kyc(pg, cid, txn_dict)
    wn, ws = await build_aop_bundle_narrative(
        customer_id=cid,
        customer_name=cust.customer_name,
        account_product=body.account_product.strip() or "Savings",
        risk_rating=body.risk_rating.strip() or "medium",
        str_notes_summary=None,
        use_llm=body.use_llm,
    )
    out = _draft_aop_record(
        cid,
        user,
        account_product=body.account_product.strip() or "Savings",
        risk_rating=body.risk_rating.strip() or "medium",
        word_narrative=wn,
        word_narrative_source=ws,
    )
    return out


def _normalize_upload_document_kind(raw: str) -> str:
    k = (raw or DOCUMENT_KIND_AOP_PACKAGE).strip().lower()
    return k if k in VALID_DOCUMENT_KINDS else DOCUMENT_KIND_AOP_PACKAGE


@router.post("/{customer_id}/aop-upload")
async def upload_customer_aop_form(
    request: Request,
    customer_id: str,
    file: UploadFile = File(...),
    document_kind: str = Form(DOCUMENT_KIND_AOP_PACKAGE),
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg, cid, kyc = await _resolve_customer_kyc(request, customer_id)
    if not kyc:
        raise HTTPException(status_code=404, detail="Customer not found")
    content = await file.read()
    if len(content) > _AOP_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 20 MB)")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _AOP_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type; use PDF, Word, or image (.pdf, .doc, .docx, .jpg, .jpeg, .png)",
        )
    dk = _normalize_upload_document_kind(document_kind)
    disk = write_aop_to_disk(
        cid,
        original_filename=(file.filename or "aop-form").strip() or "aop-form",
        content=content,
        file_suffix=suffix,
    )
    disk["document_kind"] = dk
    persisted = False
    if pg is not None:
        try:
            await insert_aop_upload_row(
                pg,
                customer_id=cid,
                upload_id=str(disk["upload_id"]),
                filename=str(disk["filename"]),
                stored_filename=str(disk["stored_filename"]),
                size_bytes=int(disk["size"]),
                uploaded_at_iso=str(disk["uploaded_at"]),
                uploaded_by_email=_actor_email(user),
                document_kind=dk,
            )
            persisted = True
        except Exception:
            register_in_memory_catalog(cid, disk)
    else:
        register_in_memory_catalog(cid, disk)
    meta = {
        "upload_id": disk["upload_id"],
        "filename": disk["filename"],
        "uploaded_at": disk["uploaded_at"],
        "size": disk["size"],
        "persisted": persisted,
        "document_kind": dk,
    }
    audit_trail.record_event_from_user(
        user,
        action="customer.aop.uploaded",
        resource_type="customer",
        resource_id=cid,
        details={
            "upload_id": meta["upload_id"],
            "filename": meta["filename"],
            "size": meta["size"],
            "persisted_to_database": persisted,
        },
    )
    return meta


@router.get("/{customer_id}/aop-upload/{upload_id}/download")
async def download_customer_aop_upload(
    request: Request,
    customer_id: str,
    upload_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _ = user
    cid = customer_id.strip()
    uid = upload_id.strip()
    pg = getattr(request.app.state, "pg", None)
    p = await _aop_download_path(pg, cid, uid)
    if p is None or not p.is_file():
        raise HTTPException(status_code=404, detail="Upload not found")
    fname = uid
    if pg is not None:
        try:
            row = await fetch_aop_upload_row(pg, cid, uid)
            if row:
                fname = str(row.get("filename") or fname)
        except Exception:
            pass
    if fname == uid:
        rec = get_record(cid, uid)
        if rec:
            fname = str(rec.get("filename") or fname)
    return FileResponse(str(p), filename=fname, media_type="application/octet-stream")


@router.get("/{customer_id}/aop-upload/bundle")
async def download_customer_supporting_documents_bundle(
    request: Request,
    customer_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    scope: str = Query(
        "all",
        description="all = every upload; otc_estr_supporting = profile_change + cash_threshold only; aop_package = AOP files only",
    ),
):
    """
    Merge customer uploads into one PDF (PDF pages + images; Word as placeholder pages).

    Use ``scope=otc_estr_supporting`` for OTC ESTR supporting evidence (excludes AOP package uploads).
    Use ``scope=aop_package`` for account-opening package file uploads only.
    ``scope=all`` merges every categorized upload (legacy / full archive).
    """
    pg, cid, kyc = await _resolve_customer_kyc(request, customer_id)
    if not kyc:
        raise HTTPException(status_code=404, detail="Customer not found")
    sc = (scope or "all").strip().lower()
    if sc not in ("all", "otc_estr_supporting", "aop_package"):
        raise HTTPException(status_code=400, detail="scope must be all, otc_estr_supporting, or aop_package")
    uploads = await _merged_aop_uploads_for_api(pg, cid)
    if sc == "otc_estr_supporting":
        uploads = [
            u
            for u in uploads
            if str(u.get("document_kind") or "") in ("profile_change", "cash_threshold")
        ]
    elif sc == "aop_package":
        uploads = [u for u in uploads if str(u.get("document_kind") or "") == DOCUMENT_KIND_AOP_PACKAGE]
    uploads_asc = sorted(uploads, key=lambda x: str(x.get("uploaded_at") or ""))
    items: List[Tuple[Path, str]] = []
    for u in uploads_asc:
        uid = str(u.get("upload_id") or "").strip()
        if not uid:
            continue
        p = await _aop_download_path(pg, cid, uid)
        if p is not None and p.is_file():
            items.append((p, str(u.get("filename") or p.name)))

    display_name = str(kyc.customer_name or "").strip() or cid
    pdf_bytes = merge_customer_files_to_pdf(items, customer_display_name=display_name)
    variant = "full" if sc == "all" else sc
    fname = supporting_bundle_download_filename(display_name, variant=variant)
    audit_trail.record_event_from_user(
        user,
        action="customer.supporting_bundle.downloaded",
        resource_type="customer",
        resource_id=cid,
        details={"filename": fname, "source_files": len(items), "scope": sc},
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/{customer_id}/walk-in-transaction", response_model=TransactionResponse)
async def walk_in_transaction(
    request: Request,
    customer_id: str,
    body: WalkInBody,
    background: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
):
    pg, cid, kyc = await _resolve_customer_kyc(request, customer_id)
    if not kyc:
        raise HTTPException(
            status_code=404,
            detail="Customer not found. Save KYC on the Customers page before recording walk-in cash.",
        )
    tt = "cash_deposit" if body.direction == "deposit" else "cash_withdrawal"
    narrative = (body.narrative or "").strip() or f"OTC branch walk-in {body.direction}: cash {body.direction}"
    txn = TransactionResponse(
        customer_id=cid,
        amount=float(body.amount),
        currency=(body.currency or "NGN").strip() or "NGN",
        transaction_type=tt,
        narrative=narrative[:2000],
        metadata={"channel": "otc_branch", "walk_in": True, "walk_in_direction": body.direction},
        status="received",
        created_at=datetime.utcnow(),
    )
    _persist_txn_geo(txn)
    background.add_task(_process_transaction_async, txn.id, pg)
    audit_trail.record_event_from_user(
        user,
        action="transaction.walk_in.ingested",
        resource_type="transaction",
        resource_id=txn.id,
        details={"customer_id": cid, "direction": body.direction, "amount": body.amount, "currency": txn.currency},
    )
    return txn
