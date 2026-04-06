"""On-disk AOP files and optional in-memory catalog when Postgres metadata insert is unavailable."""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AOP_UPLOAD_DIR = _REPO_ROOT / "uploads" / "aop"

# customer_id -> list of records (each has private _path); used only when DB row not saved
_CATALOG: Dict[str, List[Dict[str, Any]]] = {}


def _ensure_dir() -> None:
    AOP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def clear_aop_upload_catalog() -> None:
    """Remove all uploaded files and reset the in-memory catalog (e.g. on demo re-seed)."""
    if AOP_UPLOAD_DIR.is_dir():
        try:
            shutil.rmtree(AOP_UPLOAD_DIR)
        except Exception:
            pass
    _CATALOG.clear()
    _ensure_dir()


def write_aop_to_disk(
    customer_id: str, *, original_filename: str, content: bytes, file_suffix: str
) -> Dict[str, Any]:
    """Write bytes under uploads/aop/. Returns metadata including _path (do not return _path to API)."""
    _ensure_dir()
    upload_id = uuid4().hex
    stem = Path(original_filename or "aop").stem
    stem_safe = re.sub(r"[^a-zA-Z0-9._-]", "_", stem)[:80]
    ext = file_suffix if file_suffix.startswith(".") else f".{file_suffix}"
    dest_name = f"{customer_id}_{upload_id}_{stem_safe}{ext}"
    dest = AOP_UPLOAD_DIR / dest_name
    dest.write_bytes(content)
    uploaded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "upload_id": upload_id,
        "filename": original_filename or dest_name,
        "uploaded_at": uploaded_at,
        "size": len(content),
        "stored_filename": dest.name,
        "_path": dest,
    }


def register_in_memory_catalog(customer_id: str, disk_result: Dict[str, Any]) -> None:
    rec = {
        "upload_id": disk_result["upload_id"],
        "filename": disk_result["filename"],
        "uploaded_at": disk_result["uploaded_at"],
        "size": disk_result["size"],
        "persisted": False,
        "document_kind": str(disk_result.get("document_kind") or "aop_package"),
        "_path": disk_result["_path"],
    }
    _CATALOG.setdefault(customer_id, []).append(rec)


def save_upload(
    customer_id: str, *, original_filename: str, content: bytes, file_suffix: str
) -> Dict[str, Any]:
    """Write file and register in memory only (no Postgres)."""
    res = write_aop_to_disk(customer_id, original_filename=original_filename, content=content, file_suffix=file_suffix)
    register_in_memory_catalog(customer_id, res)
    return public_aop_meta(res)


def public_aop_meta(disk_or_rec: Dict[str, Any], *, persisted: Optional[bool] = None) -> Dict[str, Any]:
    out = {
        "upload_id": disk_or_rec["upload_id"],
        "filename": disk_or_rec["filename"],
        "uploaded_at": disk_or_rec["uploaded_at"],
        "size": disk_or_rec["size"],
    }
    if persisted is not None:
        out["persisted"] = persisted
    elif "persisted" in disk_or_rec:
        out["persisted"] = disk_or_rec["persisted"]
    return out


def list_uploads_public(customer_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rec in _CATALOG.get(customer_id, []):
        out.append(
            {
                "upload_id": rec["upload_id"],
                "filename": rec["filename"],
                "uploaded_at": rec["uploaded_at"],
                "size": rec["size"],
                "persisted": rec.get("persisted", False),
                "document_kind": str(rec.get("document_kind") or "aop_package"),
            }
        )
    return out


def memory_upload_count(customer_id: str) -> int:
    return len(_CATALOG.get(customer_id, []))


def customer_ids_with_memory_aop() -> set[str]:
    return {cid for cid, recs in _CATALOG.items() if recs}


def get_record(customer_id: str, upload_id: str) -> Optional[Dict[str, Any]]:
    for rec in _CATALOG.get(customer_id, []):
        if rec["upload_id"] == upload_id:
            return rec
    return None
