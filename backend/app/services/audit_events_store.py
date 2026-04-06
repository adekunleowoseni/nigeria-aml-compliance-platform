"""
Append-only audit persistence: ``audit_events`` via SECURITY DEFINER ``append_audit_event``.

Hash chain (per spec):
  chain_hash = SHA256( id || '|' || timestamp || '|' || actor || '|' || action || '|' || prev_hash || '|' || nonce )
All UTF-8. Timestamp is ISO-8601 UTC with microsecond precision ending in Z.

Writes use a connection pool; chain tip reads are serialized with a process lock for correctness under concurrency.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    ConnectionPool = None  # type: ignore
    dict_row = None  # type: ignore

import uuid

_pool: Optional[Any] = None
_pool_lock = threading.Lock()
_write_lock = threading.RLock()
_ZERO = "0" * 64


def _ts_iso_for_hash(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    s = dt.isoformat(timespec="microseconds")
    if s.endswith("+00:00"):
        return s[:-6] + "Z"
    return s.replace("+00:00", "Z")


def compute_chain_hash(
    *,
    event_id: str,
    ts: datetime,
    actor: str,
    action: str,
    prev_hash: str,
    nonce: str,
) -> str:
    raw = f"{event_id}|{_ts_iso_for_hash(ts)}|{actor}|{action}|{prev_hash}|{nonce}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def init_pool(dsn: str, *, min_size: int = 2, max_size: int = 32) -> None:
    global _pool
    if ConnectionPool is None:
        raise RuntimeError("psycopg[pool] is required for audit_events_store")
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.close()
            except Exception:
                pass
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=max(1, min_size),
            max_size=max(2, max_size),
            open=True,
            kwargs={"autocommit": False},
        )


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.close()
            except Exception:
                pass
            _pool = None


def _row_to_api_event(row: Dict[str, Any]) -> Dict[str, Any]:
    ts = row["ts"]
    if not isinstance(ts, datetime):
        ts = datetime.now(timezone.utc)
    details = row.get("details") or {}
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            details = {}
    eid = str(row["id"])
    return {
        "id": eid,
        "sequence": int(row["sequence"]),
        "timestamp": _ts_iso_for_hash(ts),
        "actor": row.get("actor") or "",
        "action": row.get("action") or "",
        "prev_hash": (row.get("prev_hash") or "").strip(),
        "prev_chain_hash": (row.get("prev_hash") or "").strip(),
        "nonce": row.get("nonce") or "",
        "chain_hash": (row.get("chain_hash") or "").strip(),
        "integrity_hash": (row.get("chain_hash") or "").strip(),
        "resource_type": row.get("resource_type") or "",
        "resource_id": row.get("resource_id") or "",
        "actor_sub": row.get("actor_sub") or "",
        "actor_email": row.get("actor_email") or "",
        "actor_role": row.get("actor_role") or "",
        "details": details if isinstance(details, dict) else {},
        "ip_address": row.get("ip_address"),
    }


def append_event(
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    actor_sub: str,
    actor_email: str,
    actor_role: str,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> Dict[str, Any]:
    if _pool is None:
        raise RuntimeError("audit pool not initialized")

    actor = (actor_email or actor_sub or "system").strip() or "system"
    event_uuid = uuid.uuid4()
    event_id = str(event_uuid)
    ts = datetime.now(timezone.utc)
    nonce = secrets.token_hex(16)
    det = details or {}

    with _write_lock:
        with _pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (918_273_641,))
                    cur.execute(
                        "SELECT chain_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
                    )
                    r = cur.fetchone()
                    prev_hash = (r[0] or "").strip() if r and r[0] else _ZERO
                    if len(prev_hash) != 64:
                        prev_hash = _ZERO
                    chain_hash = compute_chain_hash(
                        event_id=event_id,
                        ts=ts,
                        actor=actor,
                        action=action,
                        prev_hash=prev_hash,
                        nonce=nonce,
                    )
                    cur.execute(
                        """
                        SELECT append_audit_event(
                          %s::uuid, %s::timestamptz, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s::jsonb, %s
                        )
                        """,
                        (
                            event_id,
                            ts,
                            actor,
                            action,
                            prev_hash,
                            nonce,
                            chain_hash,
                            resource_type,
                            resource_id,
                            actor_sub,
                            actor_email,
                            actor_role,
                            json.dumps(det, default=str),
                            ip_address,
                        ),
                    )
                    seq = cur.fetchone()[0]

    return {
        "id": event_id,
        "sequence": int(seq),
        "timestamp": _ts_iso_for_hash(ts),
        "actor": actor,
        "action": action,
        "prev_hash": prev_hash,
        "prev_chain_hash": prev_hash,
        "nonce": nonce,
        "chain_hash": chain_hash,
        "integrity_hash": chain_hash,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "actor_sub": actor_sub,
        "actor_email": actor_email,
        "actor_role": actor_role,
        "details": det,
        "ip_address": ip_address,
    }


def fetch_events_window(
    *,
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
    max_rows: int = 500_000,
) -> List[Dict[str, Any]]:
    max_rows = max(1, min(max_rows, 500_000))
    if _pool is None:
        return []
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if from_ts is not None and to_ts is not None:
                cur.execute(
                    """
                    SELECT * FROM audit_events
                    WHERE ts >= %s AND ts <= %s
                    ORDER BY sequence DESC
                    LIMIT %s
                    """,
                    (from_ts, to_ts, max_rows),
                )
            elif from_ts is not None:
                cur.execute(
                    """
                    SELECT * FROM audit_events
                    WHERE ts >= %s
                    ORDER BY sequence DESC
                    LIMIT %s
                    """,
                    (from_ts, max_rows),
                )
            elif to_ts is not None:
                cur.execute(
                    """
                    SELECT * FROM audit_events
                    WHERE ts <= %s
                    ORDER BY sequence DESC
                    LIMIT %s
                    """,
                    (to_ts, max_rows),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM audit_events
                    ORDER BY sequence DESC
                    LIMIT %s
                    """,
                    (max_rows,),
                )
            rows = cur.fetchall()
    return [_row_to_api_event(dict(x)) for x in rows]


def fetch_all_ordered_by_sequence(max_rows: int = 2_000_000) -> List[Dict[str, Any]]:
    max_rows = max(1, min(max_rows, 2_000_000))
    if _pool is None:
        return []
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM audit_events ORDER BY sequence ASC LIMIT %s",
                (max_rows,),
            )
            rows = cur.fetchall()
    return [_row_to_api_event(dict(x)) for x in rows]


def integrity_summary() -> Dict[str, Any]:
    if _pool is None:
        return {"total_events": 0, "first_event": None, "last_event": None, "chain_head": _ZERO}
    with _pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM audit_events")
            total = int(cur.fetchone()["c"])
            cur.execute(
                """
                SELECT * FROM audit_events ORDER BY sequence ASC LIMIT 1
                """
            )
            first = cur.fetchone()
            cur.execute(
                """
                SELECT * FROM audit_events ORDER BY sequence DESC LIMIT 1
                """
            )
            last = cur.fetchone()
    return {
        "total_events": total,
        "first_event": _row_to_api_event(dict(first)) if first else None,
        "last_event": _row_to_api_event(dict(last)) if last else None,
        "chain_head": (dict(last).get("chain_hash") or _ZERO).strip() if last else _ZERO,
    }


def verify_chain_full(*, max_events: int = 2_000_000) -> Dict[str, Any]:
    """
    Recompute every chain_hash and prev link; O(n). Suitable for regulatory verification and 10k+ rows.
    """
    rows = fetch_all_ordered_by_sequence(max_rows=max_events)
    broken: List[Dict[str, Any]] = []
    prev_link = _ZERO
    ok = True
    for ev in rows:
        seq = int(ev.get("sequence") or 0)
        ph = (ev.get("prev_hash") or "").strip()
        if ph != prev_link:
            ok = False
            broken.append(
                {
                    "sequence": seq,
                    "issue": "prev_hash_mismatch",
                    "expected_prev": prev_link,
                    "stored_prev": ph,
                }
            )
        try:
            ts = datetime.fromisoformat(str(ev.get("timestamp", "")).replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(timezone.utc)
        expected_hash = compute_chain_hash(
            event_id=str(ev.get("id") or ""),
            ts=ts,
            actor=str(ev.get("actor") or ""),
            action=str(ev.get("action") or ""),
            prev_hash=ph,
            nonce=str(ev.get("nonce") or ""),
        )
        ch = (ev.get("chain_hash") or "").strip()
        if ch != expected_hash:
            ok = False
            broken.append(
                {
                    "sequence": seq,
                    "issue": "chain_hash_mismatch",
                    "expected": expected_hash,
                    "stored": ch,
                }
            )
        prev_link = ch
    total = len(rows)
    summary = integrity_summary()
    capped = summary["total_events"] > total
    return {
        "valid": ok and not capped,
        "events_verified": total,
        "broken_links": broken,
        "chain_head": prev_link if rows else _ZERO,
        "storage": "postgres",
        "postgres_total_rows": summary["total_events"],
        "verify_truncated": capped,
        "first_event": summary.get("first_event"),
        "last_event": summary.get("last_event"),
    }
