"""Attach a shared AOP PDF template to every demo customer (named per customer for downloads)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import Request

from app.services.aop_upload_db import insert_aop_upload_row
from app.services.aop_upload_store import (
    customer_ids_with_memory_aop,
    register_in_memory_catalog,
    write_aop_to_disk,
)
from app.services.customer_kyc_db import list_customers_kyc


def _backend_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def resolve_aop_template_path() -> Optional[Path]:
    """Prefer repo-root AOPfile.pdf, then backend/demo_assets/AOP_template.pdf."""
    backend = _backend_dir()
    repo = backend.parent
    for p in (repo / "AOPfile.pdf", backend / "demo_assets" / "AOP_template.pdf"):
        if p.is_file():
            return p
    return None


def aop_display_filename(customer_name: str) -> str:
    """Human-facing name e.g. John_Doe-AOP.pdf (same PDF bytes for all customers in demo)."""
    base = (customer_name or "").strip() or "Customer"
    slug = re.sub(r"[^\w\s-]", "", base, flags=re.UNICODE)
    slug = re.sub(r"\s+", "_", slug).strip("_")[:80] or "Customer"
    return f"{slug}-AOP.pdf"


async def _customer_ids_with_any_aop(pg: Any) -> Set[str]:
    have: Set[str] = set(customer_ids_with_memory_aop())
    if pg is not None:
        try:
            rows = await pg.fetch("SELECT DISTINCT customer_id FROM aml_customer_aop_upload")
            have |= {str(r["customer_id"]) for r in rows}
        except Exception:
            pass
    return have


async def seed_demo_aop_template_for_all_customers(
    request: Request,
    *,
    uploaded_by_email: Optional[str] = None,
    max_customers: int = 25_000,
) -> Dict[str, Any]:
    """
    For each customer returned by list_customers_kyc (merged demo sources), copy the template PDF once
    if that customer has no AOP upload yet.
    """
    template = resolve_aop_template_path()
    if not template:
        return {"applied": 0, "skipped": True, "reason": "AOP template PDF not found (add AOPfile.pdf at repo root or backend/demo_assets/AOP_template.pdf)"}

    pdf_bytes = template.read_bytes()
    if len(pdf_bytes) > 20 * 1024 * 1024:
        return {"applied": 0, "skipped": True, "reason": "template file too large"}

    pg = getattr(request.app.state, "pg", None)
    have = await _customer_ids_with_any_aop(pg)
    rows, _ = await list_customers_kyc(
        pg, limit=max_customers, offset=0, q=None, merge_demo_sources=True
    )

    applied = 0
    for r in rows:
        cid = str(r["customer_id"]).strip()
        if not cid or cid in have:
            continue
        name = str(r.get("customer_name") or "").strip() or cid
        display_fn = aop_display_filename(name)
        disk = write_aop_to_disk(
            cid,
            original_filename=display_fn,
            content=pdf_bytes,
            file_suffix=".pdf",
        )
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
                    uploaded_by_email=uploaded_by_email,
                    document_kind="aop_package",
                )
            except Exception:
                disk["document_kind"] = "aop_package"
                register_in_memory_catalog(cid, disk)
        else:
            disk["document_kind"] = "aop_package"
            register_in_memory_catalog(cid, disk)
        have.add(cid)
        applied += 1

    return {
        "applied": applied,
        "skipped": False,
        "template": str(template),
        "persisted_to_database": pg is not None,
    }
