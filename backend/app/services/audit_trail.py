"""
Tamper-evident audit trail.

- **postgres** (default): ``audit_events`` table, hash chain
  ``SHA256(id|timestamp|actor|action|prev_hash|nonce)``, append-only (RLS + triggers + SECURITY DEFINER).
- **memory**: in-process fallback for dev when Postgres is unavailable.

Regulatory retention: export / partition archives; rows in ``audit_events`` are not deleted by the app.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.core.logging import get_logger

log = get_logger(component="audit_trail")

_lock = threading.Lock()
_EVENTS: List[Dict[str, Any]] = []
_CHAIN_HEAD = "0" * 64

_EFFECTIVE_BACKEND: Literal["memory", "postgres"] = "memory"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def configure_from_settings() -> None:
    """Call once after env loaded (e.g. FastAPI startup). Falls back to memory if Postgres pool init fails."""
    global _EFFECTIVE_BACKEND
    from app.config import settings

    want = settings.audit_trail_backend
    if want == "postgres":
        try:
            from app.services.audit_events_store import init_pool

            init_pool(settings.postgres_url)
            _EFFECTIVE_BACKEND = "postgres"
            log.info("audit_trail_backend", backend="postgres")
        except Exception:
            log.exception("audit_events_pool_init_failed")
            _EFFECTIVE_BACKEND = "memory"
            log.warning("audit_trail_backend_fallback", backend="memory")
    else:
        _EFFECTIVE_BACKEND = "memory"
        log.info("audit_trail_backend", backend="memory")


def shutdown_audit_storage() -> None:
    if _EFFECTIVE_BACKEND == "postgres":
        try:
            from app.services.audit_events_store import close_pool

            close_pool()
        except Exception:
            log.exception("audit_events_pool_close_failed")


def get_storage_config() -> Dict[str, Any]:
    from app.config import settings

    return {
        "audit_trail_backend": _EFFECTIVE_BACKEND,
        "audit_retention_days": settings.audit_retention_days,
        "audit_retention_interval_hours": settings.audit_retention_interval_hours,
        "document_retention_note": (
            "The audit_events table is append-only (no UPDATE/DELETE). Meet retention by exporting to "
            "cold storage or attaching time-based partitions; do not mutate historical rows."
        ),
    }


def run_retention_purge() -> Dict[str, Any]:
    """Delete events older than audit_retention_days (if set). Safe to call from a background task."""
    from app.config import settings

    days = settings.audit_retention_days
    if days is None or days <= 0:
        return {"ran": False, "reason": "disabled", "removed": 0, "backend": _EFFECTIVE_BACKEND}
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    if _EFFECTIVE_BACKEND == "postgres":
        return {
            "ran": False,
            "reason": "audit_events is append-only; retention is export/archive only",
            "removed": 0,
            "backend": _EFFECTIVE_BACKEND,
        }
    else:
        removed = _purge_memory_older_than(cutoff)
    return {
        "ran": True,
        "cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
        "removed": removed,
        "backend": _EFFECTIVE_BACKEND,
    }


def _purge_memory_older_than(cutoff: datetime) -> int:
    global _CHAIN_HEAD
    with _lock:
        before = len(_EVENTS)
        kept: List[Dict[str, Any]] = []
        for ev in _EVENTS:
            evdt = _parse_iso(str(ev.get("timestamp") or ""))
            if not evdt:
                kept.append(ev)
                continue
            ev_utc = evdt.astimezone(timezone.utc) if evdt.tzinfo else evdt.replace(tzinfo=timezone.utc)
            if ev_utc >= cutoff:
                kept.append(ev)
        removed = before - len(kept)
        _EVENTS[:] = kept
    if removed > 0:
        _repair_memory_chain()
    return removed


def _repair_memory_chain() -> None:
    global _CHAIN_HEAD
    with _lock:
        _EVENTS.sort(key=lambda e: int(e.get("sequence") or 0))
        prev = "0" * 64
        for ev in _EVENTS:
            seq = int(ev.get("sequence") or 0)
            pl = {
                "action": ev.get("action"),
                "resource_type": ev.get("resource_type"),
                "resource_id": ev.get("resource_id"),
                "actor_sub": ev.get("actor_sub"),
                "actor_email": ev.get("actor_email"),
                "actor_role": ev.get("actor_role"),
                "details": ev.get("details") or {},
                "ip_address": ev.get("ip_address"),
            }
            canonical = json.dumps(pl, sort_keys=True, default=str, separators=(",", ":"))
            h = hashlib.sha256(f"{prev}|{seq}|{canonical}".encode("utf-8")).hexdigest()
            ev["prev_chain_hash"] = prev
            ev["integrity_hash"] = h
            prev = h
        _CHAIN_HEAD = prev if _EVENTS else "0" * 64


def _actor(user: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
    if not user:
        return "system", "system", "system"
    sub = str(user.get("sub") or user.get("email") or "unknown")
    email = str(user.get("email") or user.get("sub") or sub)
    role = str(user.get("role") or "")
    return sub, email, role


def record_event(
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
    """Append one audit event (thread-safe)."""
    if _EFFECTIVE_BACKEND == "postgres":
        try:
            from app.services.audit_events_store import append_event as pg_append

            return pg_append(
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                actor_sub=actor_sub,
                actor_email=actor_email,
                actor_role=actor_role,
                details=details,
                ip_address=ip_address,
            )
        except Exception:
            log.exception("audit_events_append_failed_fallback_memory")

    global _CHAIN_HEAD
    payload = {
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "actor_sub": actor_sub,
        "actor_email": actor_email,
        "actor_role": actor_role,
        "details": details or {},
        "ip_address": ip_address,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    with _lock:
        seq = len(_EVENTS) + 1
        block_input = f"{_CHAIN_HEAD}|{seq}|{canonical}"
        integrity_hash = hashlib.sha256(block_input.encode("utf-8")).hexdigest()
        event: Dict[str, Any] = {
            "id": f"AUD-{seq:09d}",
            "sequence": seq,
            "timestamp": _utc_now_iso(),
            "prev_chain_hash": _CHAIN_HEAD,
            "integrity_hash": integrity_hash,
            **payload,
        }
        _EVENTS.append(event)
        _CHAIN_HEAD = integrity_hash
        return dict(event)


def record_event_from_user(
    user: Dict[str, Any],
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> Dict[str, Any]:
    sub, email, role = _actor(user)
    return record_event(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_sub=sub,
        actor_email=email,
        actor_role=role,
        details=details,
        ip_address=ip_address,
    )


def record_report_generated(user: Dict[str, Any], report_id: str, rec: Dict[str, Any], *, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rt = str(rec.get("type") or "UNKNOWN").lower()
    txn = rec.get("txn") if isinstance(rec.get("txn"), dict) else {}
    details: Dict[str, Any] = {
        "report_type": rec.get("type"),
        "status": rec.get("status"),
        "customer_id": rec.get("customer_id"),
        "alert_id": rec.get("alert_id"),
        "change_type": rec.get("change_type"),
        "transaction_id": txn.get("id") if isinstance(txn, dict) else None,
        "activity_basis": rec.get("activity_basis"),
        "narrative_source": rec.get("narrative_source"),
    }
    if extra:
        details.update(extra)
    return record_event_from_user(
        user,
        action=f"report.generated.{rt}",
        resource_type="regulatory_report",
        resource_id=report_id,
        details={k: v for k, v in details.items() if v is not None},
    )


def record_login_failure(*, attempted_email: str, reason: str) -> Dict[str, Any]:
    return record_event(
        action="auth.login.failure",
        resource_type="identity",
        resource_id=attempted_email.strip().lower()[:128] or "unknown",
        actor_sub="anonymous",
        actor_email=attempted_email.strip().lower()[:256] or "unknown",
        actor_role="anonymous",
        details={"reason": reason},
    )


def record_login_success(*, email: str, role: str, display_name: str) -> Dict[str, Any]:
    return record_event(
        action="auth.login.success",
        resource_type="identity",
        resource_id=email.strip().lower(),
        actor_sub=email.strip().lower(),
        actor_email=email.strip().lower(),
        actor_role=role,
        details={"display_name": display_name},
    )


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts or not str(ts).strip():
        return None
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def query_events(
    *,
    skip: int = 0,
    limit: int = 50,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    action_prefix: Optional[str] = None,
    action_contains: Optional[str] = None,
    resource_type: Optional[str] = None,
    actor_email: Optional[str] = None,
    q: Optional[str] = None,
    report_only: bool = False,
    report_family: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Filter events (newest first for display — reverse scan)."""
    limit = max(1, min(limit, 500))
    skip = max(0, skip)
    fdt = _parse_iso(from_ts)
    tdt = _parse_iso(to_ts)
    ap = (action_prefix or "").strip().lower()
    ac = (action_contains or "").strip().lower()
    rt = (resource_type or "").strip().lower()
    ae = (actor_email or "").strip().lower()
    qn = (q or "").strip().lower()
    rf = (report_family or "").strip().lower()

    if _EFFECTIVE_BACKEND == "postgres":
        from app.services.audit_events_store import fetch_events_window

        snapshot = fetch_events_window(from_ts=fdt, to_ts=tdt, max_rows=500_000)
    else:
        with _lock:
            snapshot = list(_EVENTS)

    def ts_ok(ev: Dict[str, Any]) -> bool:
        try:
            evdt = datetime.fromisoformat(str(ev.get("timestamp", "")).replace("Z", "+00:00"))
        except ValueError:
            return True
        if fdt and evdt < fdt:
            return False
        if tdt and evdt > tdt:
            return False
        return True

    def match(ev: Dict[str, Any]) -> bool:
        if not ts_ok(ev):
            return False
        action = str(ev.get("action") or "").lower()
        if report_only and not action.startswith("report."):
            return False
        if rf:
            parts = action.split(".")
            if rf not in parts:
                return False
        if ap and not action.startswith(ap):
            return False
        if ac and ac not in action:
            return False
        if rt and str(ev.get("resource_type") or "").lower() != rt:
            return False
        if ae and str(ev.get("actor_email") or "").lower() != ae:
            return False
        if qn:
            blob = json.dumps(ev, default=str).lower()
            if qn not in blob:
                return False
        return True

    filtered = [e for e in snapshot if match(e)]
    filtered.sort(key=lambda e: int(e.get("sequence") or 0), reverse=True)
    total = len(filtered)
    page = filtered[skip : skip + limit]
    return page, total


def verify_chain(*, max_events: int = 2_000_000) -> Dict[str, Any]:
    """Recompute integrity chain; O(n). Postgres uses hash-chain spec; memory uses legacy local chain."""
    if _EFFECTIVE_BACKEND == "postgres":
        from app.services.audit_events_store import verify_chain_full

        return verify_chain_full(max_events=max_events)
    with _lock:
        snap = list(_EVENTS)
    snap.sort(key=lambda e: int(e.get("sequence") or 0))
    prev = "0" * 64
    ok = True
    broken: List[Dict[str, Any]] = []
    for ev in snap:
        seq = int(ev.get("sequence") or 0)
        payload = {
            "action": ev.get("action"),
            "resource_type": ev.get("resource_type"),
            "resource_id": ev.get("resource_id"),
            "actor_sub": ev.get("actor_sub"),
            "actor_email": ev.get("actor_email"),
            "actor_role": ev.get("actor_role"),
            "details": ev.get("details") or {},
            "ip_address": ev.get("ip_address"),
        }
        canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        expected_prev = prev
        block_input = f"{expected_prev}|{seq}|{canonical}"
        h = hashlib.sha256(block_input.encode("utf-8")).hexdigest()
        if ev.get("prev_chain_hash") != expected_prev:
            ok = False
            broken.append(
                {
                    "sequence": seq,
                    "issue": "prev_hash_mismatch",
                    "expected_prev": expected_prev,
                    "stored_prev": ev.get("prev_chain_hash"),
                }
            )
        if ev.get("integrity_hash") != h:
            ok = False
            broken.append(
                {
                    "sequence": seq,
                    "issue": "chain_hash_mismatch",
                    "expected": h,
                    "stored": ev.get("integrity_hash"),
                }
            )
        prev = h
    first = snap[0] if snap else None
    last = snap[-1] if snap else None
    return {
        "valid": ok,
        "events_verified": len(snap),
        "broken_links": broken,
        "chain_head": prev if snap else "0" * 64,
        "first_event": first,
        "last_event": last,
        "storage": "memory",
        "postgres_total_rows": None,
        "verify_truncated": False,
    }


def governance_summary(*, from_ts: Optional[str] = None, to_ts: Optional[str] = None) -> Dict[str, Any]:
    rows, _ = query_events(skip=0, limit=100_000, from_ts=from_ts, to_ts=to_ts)
    by_action = Counter(str(e.get("action") or "") for e in rows)
    by_role = Counter(str(e.get("actor_role") or "") for e in rows)
    report_events = [e for e in rows if str(e.get("action", "")).startswith("report.")]
    return {
        "period": {"from": from_ts, "to": to_ts},
        "total_events": len(rows),
        "unique_actions": len(by_action),
        "by_action": dict(by_action.most_common(50)),
        "by_actor_role": dict(by_role.most_common(20)),
        "report_events_count": len(report_events),
    }


def export_events_csv(*, from_ts: Optional[str] = None, to_ts: Optional[str] = None) -> bytes:
    rows, _ = query_events(skip=0, limit=500_000, from_ts=from_ts, to_ts=to_ts)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "id",
            "sequence",
            "timestamp",
            "action",
            "resource_type",
            "resource_id",
            "actor_email",
            "actor_role",
            "integrity_hash",
            "details_json",
        ]
    )
    for e in sorted(rows, key=lambda x: int(x.get("sequence") or 0)):
        w.writerow(
            [
                e.get("id"),
                e.get("sequence"),
                e.get("timestamp"),
                e.get("action"),
                e.get("resource_type"),
                e.get("resource_id"),
                e.get("actor_email"),
                e.get("actor_role"),
                e.get("integrity_hash"),
                json.dumps(e.get("details") or {}, default=str),
            ]
        )
    return buf.getvalue().encode("utf-8")


def export_events_json(*, from_ts: Optional[str] = None, to_ts: Optional[str] = None) -> bytes:
    rows, total = query_events(skip=0, limit=500_000, from_ts=from_ts, to_ts=to_ts)
    rows_sorted = sorted(rows, key=lambda x: int(x.get("sequence") or 0))
    return json.dumps({"total": total, "events": rows_sorted}, indent=2, default=str).encode("utf-8")
