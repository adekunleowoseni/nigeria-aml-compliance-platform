"""Seed named AOP + OTC supporting documents for branch-reference demo customers (OTC-REF-*)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import Request

from app.models.alert import otc_report_kind_for_subject
from app.services.aop_upload_db import (
    DOCUMENT_KIND_AOP_PACKAGE,
    DOCUMENT_KIND_CASH_THRESHOLD,
    DOCUMENT_KIND_PROFILE_CHANGE,
    insert_aop_upload_row,
    list_aop_uploads_from_db,
)
from app.services.aop_upload_store import (
    customer_ids_with_memory_aop,
    list_uploads_public,
    register_in_memory_catalog,
    write_aop_to_disk,
)
from app.services.demo_aop_template_seed import aop_display_filename, resolve_aop_template_path
from app.services.otc_branch_reference_seed import list_otc_branch_reference_rows


def _backend_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def resolve_forms_template_dir() -> Path:
    """Prefer repo-root ``forms/``, then ``backend/demo_assets/forms`` (Docker)."""
    backend = _backend_dir()
    repo = backend.parent
    for p in (repo / "forms", backend / "demo_assets" / "forms"):
        if p.is_dir():
            return p
    return repo / "forms"


def customer_doc_slug(customer_name: str) -> str:
    base = (customer_name or "").strip() or "Customer"
    slug = re.sub(r"[^\w\s-]", "", base, flags=re.UNICODE)
    slug = re.sub(r"\s+", "_", slug).strip("_")[:80] or "Customer"
    return slug


def _filename_has_tag(existing_lower: List[str], tag: str) -> bool:
    needle = f"-{tag.lower()}."
    return any(needle in fn for fn in existing_lower)


async def _customer_ids_with_any_aop(pg: Any) -> Set[str]:
    have: Set[str] = set(customer_ids_with_memory_aop())
    if pg is not None:
        try:
            rows = await pg.fetch("SELECT DISTINCT customer_id FROM aml_customer_aop_upload")
            have |= {str(r["customer_id"]) for r in rows}
        except Exception:
            pass
    return have


async def _all_upload_filenames_lower(pg: Any, customer_id: str) -> List[str]:
    out: List[str] = []
    for rec in list_uploads_public(customer_id):
        out.append((rec.get("filename") or "").lower())
    if pg is not None:
        try:
            for r in await list_aop_uploads_from_db(pg, customer_id):
                out.append((r.get("filename") or "").lower())
        except Exception:
            pass
    return out


async def _persist_upload(
    pg: Any,
    customer_id: str,
    disk: Dict[str, Any],
    uploaded_by_email: Optional[str],
    *,
    document_kind: str,
) -> None:
    disk = {**disk, "document_kind": document_kind}
    if pg is not None:
        try:
            await insert_aop_upload_row(
                pg,
                customer_id=customer_id,
                upload_id=str(disk["upload_id"]),
                filename=str(disk["filename"]),
                stored_filename=str(disk["stored_filename"]),
                size_bytes=int(disk["size"]),
                uploaded_at_iso=str(disk["uploaded_at"]),
                uploaded_by_email=uploaded_by_email,
                document_kind=document_kind,
            )
        except Exception:
            register_in_memory_catalog(customer_id, disk)
    else:
        register_in_memory_catalog(customer_id, disk)


async def seed_otc_branch_reference_kyc_documents(
    request: Request,
    *,
    uploaded_by_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    For each OTC branch reference row customer (OTC-REF-*):

    - If they have no AOP upload yet, attach the shared AOP PDF named ``{Name}-AOP.pdf``.
    - **OTC ESTR** (cash): ``deposit-slip`` or ``withdrawal-slip`` image from ``forms/``.
    - **OTC ESAR** (profile): affidavit, NIN slip, newspaper publication, account activation form;
      birth certificate when the row's documents mention BIRTH; BVN linking + printout when the
      subject involves name/BVN alignment.
    """
    pg = getattr(request.app.state, "pg", None)
    forms_dir = resolve_forms_template_dir()
    have_aop: Set[str] = await _customer_ids_with_any_aop(pg)

    template_pdf = resolve_aop_template_path()
    pdf_bytes: Optional[bytes] = None
    if template_pdf and template_pdf.is_file():
        pdf_bytes = template_pdf.read_bytes()
        if len(pdf_bytes) > 20 * 1024 * 1024:
            pdf_bytes = None

    applied_aop = 0
    applied_docs = 0
    missing_templates: List[str] = []

    for row in list_otc_branch_reference_rows():
        sid = str(row["str_id"])
        cid = f"OTC-REF-{sid}"
        name = str(row.get("customer_name") or "").strip() or cid
        slug = customer_doc_slug(name)
        subj = str(row["otc_subject"])
        kind = otc_report_kind_for_subject(subj)
        docs_field = str(row.get("documents") or "")

        if pdf_bytes and cid not in have_aop:
            display_fn = aop_display_filename(name)
            disk = write_aop_to_disk(
                cid,
                original_filename=display_fn,
                content=pdf_bytes,
                file_suffix=".pdf",
            )
            await _persist_upload(pg, cid, disk, uploaded_by_email, document_kind=DOCUMENT_KIND_AOP_PACKAGE)
            have_aop.add(cid)
            applied_aop += 1

        existing = await _all_upload_filenames_lower(pg, cid)

        attachments: List[Tuple[str, str, str]] = []
        if kind == "otc_estr":
            if subj == "cash_deposit":
                attachments.append(("deposit-slip.jpg", "deposit-slip", ".jpg"))
            elif subj == "cash_withdrawal":
                attachments.append(("withdrawal-slip.jpg", "withdrawal-slip", ".jpg"))
        else:
            attachments.extend(
                [
                    ("affidavit.jpg", "affidavit", ".jpg"),
                    ("newspaper-publication.jpg", "newspaper-publication", ".jpg"),
                    ("nin.jpg", "nin", ".jpg"),
                    ("account-activation-form.png", "account-activation-form", ".png"),
                ]
            )
            if "BIRTH" in docs_field.upper():
                attachments.append(
                    (
                        "BIRTH-CERTICATE-IN-NIGERIA-FOR-USE-ABROAD-EDITED.jpeg",
                        "birth-certificate",
                        ".jpeg",
                    )
                )
            if subj in ("bvn_partial_name_change", "full_name_change", "name_and_dob_update"):
                attachments.append(("bvn-linking-form.jpg", "bvn-linking-form", ".jpg"))
                attachments.append(("bvn-printout.jpg", "bvn-printout", ".jpg"))

        for tmpl, tag, ext in attachments:
            if _filename_has_tag(existing, tag):
                continue
            path = forms_dir / tmpl
            if not path.is_file():
                if tmpl not in missing_templates:
                    missing_templates.append(tmpl)
                continue
            content = path.read_bytes()
            if len(content) > 20 * 1024 * 1024:
                continue
            display = f"{slug}-{tag}{ext}"
            disk = write_aop_to_disk(
                cid,
                original_filename=display,
                content=content,
                file_suffix=ext,
            )
            dk = DOCUMENT_KIND_CASH_THRESHOLD if kind == "otc_estr" else DOCUMENT_KIND_PROFILE_CHANGE
            await _persist_upload(pg, cid, disk, uploaded_by_email, document_kind=dk)
            existing.append(display.lower())
            applied_docs += 1

    return {
        "applied_aop": applied_aop,
        "applied_supporting_documents": applied_docs,
        "forms_dir": str(forms_dir),
        "missing_templates": missing_templates,
        "aop_template_available": pdf_bytes is not None,
    }
