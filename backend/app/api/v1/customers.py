"""Customer onboarding KYC, AOP generation, walk-in OTC transactions."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.api.v1.reports import _draft_aop_record, _latest_txn_for_customer
from app.config import settings
from app.api.v1.transactions import _persist_txn_geo, _process_transaction_async
from app.core.security import get_current_user
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
    upsert_customer_kyc_explicit,
)

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
    return {"items": out, "total": total, "page": page, "page_size": page_size}


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
