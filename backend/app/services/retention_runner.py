"""
Execute retention policies: soft-delete → registry → hard purge after grace period.
In-memory entities (alerts, transactions, reports) only update when ``include_memory`` and runner lives in API process.

audit_events rows are never deleted by this job (tamper-evident chain); policy evaluation is logged only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.db.postgres_client import PostgresClient
from app.services import audit_trail
from app.services.retention_policies_db import (
    get_active_policy,
    has_active_legal_hold,
    registry_delete,
    registry_insert,
    registry_list_ready_hard_purge,
)


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def run_retention_job(
    pg: PostgresClient,
    *,
    include_memory: bool = True,
    grace_hard_purge_days: int = 30,
    actor_email: str = "system@retention",
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    stats: Dict[str, Any] = {
        "at": now.isoformat(),
        "include_memory": include_memory,
        "soft_deleted": {},
        "hard_purged": {},
        "anonymized_kyc": 0,
        "skipped_audit_chain": True,
    }

    # --- audit_event: log only (append-only table) ---
    aud_pol = await get_active_policy(pg, "audit_event")
    if aud_pol:
        audit_trail.record_event(
            action="retention.policy_evaluated",
            resource_type="retention_policy",
            resource_id="audit_event",
            actor_sub="retention",
            actor_email=actor_email,
            actor_role="system",
            details={
                "note": "audit_events are append-only; no automated row deletion",
                "retention_days": aud_pol.get("retention_days"),
                "action": aud_pol.get("action"),
            },
        )

    grace = max(1, int(grace_hard_purge_days))

    # --- customer_kyc (Postgres) ---
    kyc_pol = await get_active_policy(pg, "customer_kyc")
    if kyc_pol and kyc_pol.get("is_active", True):
        days = int(kyc_pol.get("retention_days") or 2555)
        action = str(kyc_pol.get("action") or "DELETE").upper()
        cutoff = now - timedelta(days=days)
        rows = await pg.fetch(
            """
            SELECT customer_id, customer_name, account_number, customer_address, phone_number, id_number, updated_at
            FROM aml_customer_kyc
            WHERE deleted_at IS NULL AND anonymized_at IS NULL AND updated_at < $1
            """,
            cutoff,
        )
        kyc_soft = 0
        kyc_anon = 0
        for row in rows:
            cid = str(row["customer_id"])
            if await has_active_legal_hold(pg, "customer_kyc", cid):
                continue
            snap = {k: str(v) if v is not None else None for k, v in dict(row).items()}
            if action == "ANONYMIZE":
                await pg.execute(
                    """
                    UPDATE aml_customer_kyc SET
                      customer_name = '[REDACTED]',
                      customer_address = '[REDACTED]',
                      phone_number = '[REDACTED]',
                      id_number = CASE
                        WHEN LENGTH(TRIM(COALESCE(id_number,''))) > 4
                        THEN '****' || RIGHT(TRIM(id_number), 4)
                        ELSE '[REDACTED]'
                      END,
                      anonymized_at = NOW(),
                      updated_at = NOW()
                    WHERE customer_id = $1 AND anonymized_at IS NULL
                    """,
                    cid,
                )
                kyc_anon += 1
                audit_trail.record_event(
                    action="retention.record_anonymized",
                    resource_type="customer_kyc",
                    resource_id=cid,
                    actor_sub="retention",
                    actor_email=actor_email,
                    actor_role="system",
                    details={"action": "ANONYMIZE"},
                )
            else:
                hp = now + timedelta(days=grace)
                await registry_insert(pg, record_type="customer_kyc", record_id=cid, snapshot=snap, hard_purge_after=hp)
                await pg.execute(
                    "UPDATE aml_customer_kyc SET deleted_at = NOW(), updated_at = NOW() WHERE customer_id = $1",
                    cid,
                )
                kyc_soft += 1
                audit_trail.record_event(
                    action="retention.record_soft_deleted",
                    resource_type="customer_kyc",
                    resource_id=cid,
                    actor_sub="retention",
                    actor_email=actor_email,
                    actor_role="system",
                    details={"hard_purge_after": hp.isoformat()},
                )
        stats["soft_deleted"]["customer_kyc"] = kyc_soft
        stats["anonymized_kyc"] = kyc_anon

    # --- hard purge from registry (Postgres + memory keys) ---
    ready = await registry_list_ready_hard_purge(pg, before=now, limit=500)
    hp_counts: Dict[str, int] = {}
    for reg in ready:
        rt = str(reg.get("record_type") or "")
        rid = str(reg.get("record_id") or "")
        if await has_active_legal_hold(pg, rt, rid):
            continue
        if rt == "customer_kyc":
            await pg.execute("DELETE FROM aml_customer_kyc WHERE customer_id = $1", rid)
        elif include_memory and rt == "alert":
            from app.api.v1.in_memory_stores import _ALERTS

            _ALERTS.pop(rid, None)
        elif include_memory and rt == "transaction":
            from app.api.v1.in_memory_stores import _TXNS

            _TXNS.pop(rid, None)
        elif include_memory and rt == "report":
            from app.api.v1.reports import _REPORTS

            _REPORTS.pop(rid, None)
        await registry_delete(pg, rt, rid)
        hp_counts[rt] = hp_counts.get(rt, 0) + 1
        audit_trail.record_event(
            action="retention.record_hard_purged",
            resource_type=rt,
            resource_id=rid,
            actor_sub="retention",
            actor_email=actor_email,
            actor_role="system",
            details={"source": "registry"},
        )
    stats["hard_purged"] = hp_counts

    if not include_memory:
        return stats

    # --- alerts (memory) ---
    ap = await get_active_policy(pg, "alert")
    if ap and ap.get("is_active", True):
        days = int(ap.get("retention_days") or 365)
        cutoff = now - timedelta(days=days)
        from app.api.v1.in_memory_stores import _ALERTS

        n = 0
        for aid, a in list(_ALERTS.items()):
            if getattr(a, "deleted_at", None):
                continue
            created = _utc(a.created_at)
            if not created or created > cutoff:
                continue
            if await has_active_legal_hold(pg, "alert", aid):
                continue
            snap = a.model_dump(mode="json")
            hp = now + timedelta(days=grace)
            await registry_insert(pg, record_type="alert", record_id=aid, snapshot=snap, hard_purge_after=hp)
            _ALERTS[aid] = a.model_copy(update={"deleted_at": now, "updated_at": now})
            n += 1
            audit_trail.record_event(
                action="retention.record_soft_deleted",
                resource_type="alert",
                resource_id=aid,
                actor_sub="retention",
                actor_email=actor_email,
                actor_role="system",
                details={"hard_purge_after": hp.isoformat()},
            )
        stats["soft_deleted"]["alert"] = n

    # --- transactions (memory) ---
    tp = await get_active_policy(pg, "transaction")
    if tp and tp.get("is_active", True):
        days = int(tp.get("retention_days") or 365)
        cutoff = now - timedelta(days=days)
        from app.api.v1.in_memory_stores import _TXNS

        n = 0
        for tid, t in list(_TXNS.items()):
            if getattr(t, "deleted_at", None):
                continue
            created = _utc(t.created_at)
            if not created or created > cutoff:
                continue
            if await has_active_legal_hold(pg, "transaction", tid):
                continue
            snap = t.model_dump(mode="json")
            hp = now + timedelta(days=grace)
            await registry_insert(pg, record_type="transaction", record_id=tid, snapshot=snap, hard_purge_after=hp)
            _TXNS[tid] = t.model_copy(update={"deleted_at": now, "updated_at": now})
            n += 1
            audit_trail.record_event(
                action="retention.record_soft_deleted",
                resource_type="transaction",
                resource_id=tid,
                actor_sub="retention",
                actor_email=actor_email,
                actor_role="system",
                details={"hard_purge_after": hp.isoformat()},
            )
        stats["soft_deleted"]["transaction"] = n

    # --- reports (memory dict) ---
    rp = await get_active_policy(pg, "report")
    if rp and rp.get("is_active", True):
        days = int(rp.get("retention_days") or 1825)
        cutoff = now - timedelta(days=days)
        from app.api.v1.reports import _REPORTS

        n = 0
        for rid, rec in list(_REPORTS.items()):
            if not isinstance(rec, dict) or rec.get("deleted_at"):
                continue
            raw = rec.get("created_at") or rec.get("generated_at")
            if isinstance(raw, datetime):
                cdt = _utc(raw)
            elif isinstance(raw, str):
                try:
                    cdt = _utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
                except ValueError:
                    cdt = None
            else:
                cdt = None
            if not cdt or cdt > cutoff:
                continue
            if await has_active_legal_hold(pg, "report", rid):
                continue
            hp = now + timedelta(days=grace)
            await registry_insert(pg, record_type="report", record_id=rid, snapshot=dict(rec), hard_purge_after=hp)
            rec2 = dict(rec)
            rec2["deleted_at"] = now.isoformat()
            _REPORTS[rid] = rec2
            n += 1
            audit_trail.record_event(
                action="retention.record_soft_deleted",
                resource_type="report",
                resource_id=rid,
                actor_sub="retention",
                actor_email=actor_email,
                actor_role="system",
                details={"hard_purge_after": hp.isoformat()},
            )
        stats["soft_deleted"]["report"] = n

    return stats
