"""Postgres persistence for customer AOP file uploads (metadata + on-disk filename)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db.postgres_client import PostgresClient
from app.services.aop_upload_store import AOP_UPLOAD_DIR, list_uploads_public

# Account opening package files (excluded from OTC ESTR supporting-doc merge).
DOCUMENT_KIND_AOP_PACKAGE = "aop_package"
# Evidence when customer changes profile / identity details (OTC ESAR path).
DOCUMENT_KIND_PROFILE_CHANGE = "profile_change"
# Evidence for cash deposit/withdrawal over threshold (OTC ESTR path).
DOCUMENT_KIND_CASH_THRESHOLD = "cash_threshold"

VALID_DOCUMENT_KINDS = frozenset(
    {DOCUMENT_KIND_AOP_PACKAGE, DOCUMENT_KIND_PROFILE_CHANGE, DOCUMENT_KIND_CASH_THRESHOLD}
)


async def ensure_aml_customer_aop_upload_table(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS aml_customer_aop_upload (
            upload_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            uploaded_by_email TEXT
        )
        """
    )
    await pg.execute(
        "CREATE INDEX IF NOT EXISTS idx_aop_upload_customer ON aml_customer_aop_upload (customer_id)"
    )
    await pg.execute(
        """
        ALTER TABLE aml_customer_aop_upload
        ADD COLUMN IF NOT EXISTS document_kind TEXT NOT NULL DEFAULT 'aop_package'
        """
    )
    await pg.execute(
        "CREATE INDEX IF NOT EXISTS idx_aop_upload_customer_kind ON aml_customer_aop_upload (customer_id, document_kind)"
    )


def _iso_z(dt: Any) -> str:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return str(dt)


def _parse_uploaded_at_iso(s: str) -> datetime:
    x = (s or "").strip()
    if x.endswith("Z"):
        x = x[:-1] + "+00:00"
    return datetime.fromisoformat(x)


async def insert_aop_upload_row(
    pg: PostgresClient,
    *,
    customer_id: str,
    upload_id: str,
    filename: str,
    stored_filename: str,
    size_bytes: int,
    uploaded_at_iso: str,
    uploaded_by_email: Optional[str],
    document_kind: str = DOCUMENT_KIND_AOP_PACKAGE,
) -> None:
    uploaded_at = _parse_uploaded_at_iso(uploaded_at_iso)
    dk = (document_kind or DOCUMENT_KIND_AOP_PACKAGE).strip().lower()
    if dk not in VALID_DOCUMENT_KINDS:
        dk = DOCUMENT_KIND_AOP_PACKAGE
    await pg.execute(
        """
        INSERT INTO aml_customer_aop_upload (
            upload_id, customer_id, filename, stored_filename, size_bytes, uploaded_at, uploaded_by_email, document_kind
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        upload_id,
        customer_id,
        filename,
        stored_filename,
        size_bytes,
        uploaded_at,
        uploaded_by_email,
        dk,
    )


async def list_aop_uploads_from_db(
    pg: PostgresClient, customer_id: str, *, kinds: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    if kinds:
        rows = await pg.fetch(
            """
            SELECT upload_id, filename, stored_filename, size_bytes, uploaded_at, uploaded_by_email, document_kind
            FROM aml_customer_aop_upload
            WHERE customer_id = $1 AND document_kind = ANY($2::text[])
            ORDER BY uploaded_at DESC
            """,
            customer_id,
            kinds,
        )
    else:
        rows = await pg.fetch(
            """
            SELECT upload_id, filename, stored_filename, size_bytes, uploaded_at, uploaded_by_email, document_kind
            FROM aml_customer_aop_upload
            WHERE customer_id = $1
            ORDER BY uploaded_at DESC
            """,
            customer_id,
        )
    out: List[Dict[str, Any]] = []
    for r in rows:
        p = AOP_UPLOAD_DIR / str(r["stored_filename"])
        out.append(
            {
                "upload_id": r["upload_id"],
                "filename": r["filename"],
                "uploaded_at": _iso_z(r["uploaded_at"]),
                "size": int(r["size_bytes"]),
                "persisted": True,
                "document_kind": str(r.get("document_kind") or DOCUMENT_KIND_AOP_PACKAGE),
                "_path": p,
            }
        )
    return out


async def fetch_aop_upload_row(
    pg: PostgresClient, customer_id: str, upload_id: str
) -> Optional[Dict[str, Any]]:
    r = await pg.fetchrow(
        """
        SELECT upload_id, customer_id, filename, stored_filename, size_bytes, uploaded_at, document_kind
        FROM aml_customer_aop_upload
        WHERE customer_id = $1 AND upload_id = $2
        """,
        customer_id,
        upload_id,
    )
    if not r:
        return None
    p = AOP_UPLOAD_DIR / str(r["stored_filename"])
    return {**dict(r), "_path": p}


async def delete_all_aop_upload_rows(pg: PostgresClient) -> None:
    try:
        await pg.execute("DELETE FROM aml_customer_aop_upload")
    except Exception:
        pass


async def fetch_primary_aop_per_customer(
    pg: Optional[PostgresClient], customer_ids: List[str]
) -> Dict[str, Dict[str, str]]:
    """Latest AOP upload per customer (DB first, then in-memory catalog)."""
    out: Dict[str, Dict[str, str]] = {}
    if not customer_ids:
        return out
    if pg is not None:
        try:
            rows = await pg.fetch(
                """
                SELECT DISTINCT ON (customer_id) customer_id, upload_id, filename
                FROM aml_customer_aop_upload
                WHERE customer_id = ANY($1::text[])
                  AND document_kind = 'aop_package'
                ORDER BY customer_id, uploaded_at DESC
                """,
                customer_ids,
            )
            for r in rows:
                cid = str(r["customer_id"])
                out[cid] = {"upload_id": str(r["upload_id"]), "filename": str(r["filename"])}
        except Exception:
            pass
    for cid in customer_ids:
        if cid in out:
            continue
        mem = list_uploads_public(cid)
        if not mem:
            continue
        mem_sorted = sorted(mem, key=lambda x: str(x.get("uploaded_at") or ""), reverse=True)
        u = mem_sorted[0]
        out[cid] = {"upload_id": str(u["upload_id"]), "filename": str(u["filename"])}
    return out


async def aop_upload_counts_for_customers(
    pg: PostgresClient, customer_ids: List[str]
) -> Dict[str, int]:
    if not customer_ids:
        return {}
    try:
        rows = await pg.fetch(
            """
            SELECT customer_id, COUNT(*)::int AS c
            FROM aml_customer_aop_upload
            WHERE customer_id = ANY($1::text[])
            GROUP BY customer_id
            """,
            customer_ids,
        )
        return {str(r["customer_id"]): int(r["c"]) for r in rows}
    except Exception:
        return {}
