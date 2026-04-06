"""
Board / ECO / Management MI aggregates (CBN-style packs).
Pulls from in-memory alerts/reports plus audit summary and FTR rows where available.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.api.v1.alerts import _alerts_dashboard_payload
from app.api.v1.in_memory_stores import _ALERTS, _TXNS
from app.db.postgres_client import PostgresClient
from app.models.alert import AlertResponse
from app.services import audit_trail
from app.services.zone_branch import user_has_full_data_access, txn_matches_user_scope
from app.services.ftr_reports_db import list_ftrs


def _alert_not_soft_deleted(a: AlertResponse) -> bool:
    return getattr(a, "deleted_at", None) is None


def _alert_visible_to_user(user: Dict[str, Any], a: AlertResponse) -> bool:
    t = _TXNS.get(a.transaction_id)
    if t:
        return txn_matches_user_scope(user, t.metadata, t.customer_id)
    return txn_matches_user_scope(user, None, a.customer_id)


def mi_scope_alerts(user: Dict[str, Any]) -> List[AlertResponse]:
    if user_has_full_data_access(user):
        return [a for a in _ALERTS.values() if _alert_not_soft_deleted(a)]
    return [a for a in _ALERTS.values() if _alert_visible_to_user(user, a) and _alert_not_soft_deleted(a)]


def material_escalations(alerts: List[AlertResponse]) -> List[AlertResponse]:
    """CBN MI: CCO-track escalation and not closed / resolved (legacy: status escalated)."""
    out: List[AlertResponse] = []
    for a in alerts:
        st = (a.status or "").lower()
        if st in ("closed", "resolved"):
            continue
        if getattr(a, "escalated_to_cco", False) or st == "escalated":
            out.append(a)
    return out


def _str_ctr_counts_from_reports(_reports: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    str_n = sum(1 for r in _reports.values() if r.get("type") == "STR")
    str_sub = sum(1 for r in _reports.values() if r.get("type") == "STR" and r.get("status") == "submitted")
    ctr_n = sum(1 for r in _reports.values() if r.get("type") == "CTR")
    return {"str_total": str_n, "str_submitted": str_sub, "ctr_total": ctr_n}


def _audit_tuning_exam_counts(gov: Dict[str, Any]) -> Dict[str, int]:
    by_action = gov.get("by_action") or {}
    if not isinstance(by_action, dict):
        return {"tuning_events": 0, "exam_related_events": 0}
    tuning = 0
    exam = 0
    for act, n in by_action.items():
        al = str(act).lower()
        if "model" in al or "tuning" in al or "threshold" in al or "anomaly" in al:
            tuning += int(n) if isinstance(n, int) else 0
        if "exam" in al or "regulatory" in al or "supervisor" in al:
            exam += int(n) if isinstance(n, int) else 0
    return {"tuning_events": tuning, "exam_related_events": exam}


def _open_cases_by_analyst(alerts: List[AlertResponse]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for a in alerts:
        st = (a.status or "").lower()
        if st in ("closed",):
            continue
        inv = None
        for h in reversed(a.investigation_history or []):
            if isinstance(h, dict) and h.get("action") == "investigate" and h.get("investigator_id"):
                inv = str(h["investigator_id"])
                break
        key = inv or "unassigned"
        counts[key] += 1
    return dict(counts)


def _sanctions_adverse_counts(alerts: List[AlertResponse]) -> Dict[str, int]:
    sanctions = 0
    adverse = 0
    for a in alerts:
        md = {}
        t = _TXNS.get(a.transaction_id)
        if t and isinstance(t.metadata, dict):
            md = t.metadata
        if md.get("sanctions_hit") or md.get("sanctions_match"):
            sanctions += 1
        if md.get("adverse_media") or md.get("adverse_media_flag"):
            adverse += 1
        summ = (a.summary or "").lower()
        if "sanction" in summ:
            sanctions += 1
        if "adverse" in summ or "negative news" in summ:
            adverse += 1
    return {"sanctions_hits_flagged": sanctions, "adverse_media_flags": adverse}


async def build_board_pack_payload(
    user: Dict[str, Any],
    *,
    pg: Optional[PostgresClient],
    _reports: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    dashboard = _alerts_dashboard_payload(user)
    alerts = mi_scope_alerts(user)
    mat = material_escalations(alerts)
    gov = audit_trail.governance_summary()
    reg = _str_ctr_counts_from_reports(_reports)
    audit_x = _audit_tuning_exam_counts(gov)

    charts: List[Dict[str, Any]] = [
        {
            "id": "alert_severity_trend",
            "title": "Alert volume by severity (30 days)",
            "type": "line",
            "series": dashboard.get("trend_over_time") or [],
        },
        {
            "id": "open_case_ageing",
            "title": "Open case ageing",
            "type": "bar",
            "labels": ["<24h", "1–3d", "3–7d", ">7d"],
            "values": [
                (dashboard.get("open_case_ageing") or {}).get("lt_24h", 0),
                (dashboard.get("open_case_ageing") or {}).get("d1_3", 0),
                (dashboard.get("open_case_ageing") or {}).get("d3_7", 0),
                (dashboard.get("open_case_ageing") or {}).get("gt_7d", 0),
            ],
        },
        {
            "id": "str_ctr_volume",
            "title": "Regulatory report inventory (in-memory)",
            "type": "bar",
            "labels": ["STR total", "STR submitted", "CTR total"],
            "values": [reg["str_total"], reg["str_submitted"], reg["ctr_total"]],
        },
        {
            "id": "severity_distribution",
            "title": "Current alerts by severity band",
            "type": "bar",
            "labels": ["critical", "high", "medium", "low"],
            "values": [
                (dashboard.get("counts_by_severity") or {}).get("critical", 0),
                (dashboard.get("counts_by_severity") or {}).get("high", 0),
                (dashboard.get("counts_by_severity") or {}).get("medium", 0),
                (dashboard.get("counts_by_severity") or {}).get("low", 0),
            ],
        },
        {
            "id": "outcome_pipeline",
            "title": "Disposition pipeline",
            "type": "bar",
            "labels": list((dashboard.get("outcome_summary") or {}).keys()),
            "values": list((dashboard.get("outcome_summary") or {}).values()),
        },
        {
            "id": "material_escalations_age",
            "title": "Material escalations (CCO track, not closed)",
            "type": "line",
            "note": "Count snapshot; members listed in kpi.material_escalation_alert_ids_sample",
            "series": [{"date": datetime.now(timezone.utc).date().isoformat(), "count": len(mat)}],
        },
    ]

    ftr_pending = 0
    ftr_avg_lag_days: Optional[float] = None
    if pg is not None:
        try:
            rows, _ = await list_ftrs(pg, limit=200, skip=0, status="DRAFT")
            ftr_pending = len(rows)
            lags: List[float] = []
            for row in rows:
                vd = row.get("value_date")
                if hasattr(vd, "isoformat"):
                    vd_d = vd if isinstance(vd, date) else date.fromisoformat(str(vd)[:10])
                    lags.append((datetime.now(timezone.utc).date() - vd_d).days)
            if lags:
                ftr_avg_lag_days = round(sum(lags) / len(lags), 2)
        except Exception:
            pass

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audience": "board_of_directors",
        "kpi": {
            "total_alerts": len(alerts),
            "str_filed_submitted": reg["str_submitted"],
            "str_drafts": max(0, reg["str_total"] - reg["str_submitted"]),
            "open_alerts_ageing_over_7_days": (dashboard.get("open_case_ageing") or {}).get("gt_7d", 0),
            "material_escalations_count": len(mat),
            "material_escalation_alert_ids_sample": [x.id for x in mat[:20]],
            "pending_cco_str_approvals": dashboard.get("pending_cco_str_approvals", 0),
            "tuning_related_audit_events": audit_x["tuning_events"],
            "regulatory_exam_related_audit_events": audit_x["exam_related_events"],
            "ftr_drafts_pending": ftr_pending,
            "ftr_avg_value_date_lag_days": ftr_avg_lag_days,
        },
        "dashboard": dashboard,
        "audit_governance_summary": {
            "total_events": gov.get("total_events"),
            "report_events_count": gov.get("report_events_count"),
            "unique_actions": gov.get("unique_actions"),
        },
        "charts": charts,
        "disclaimer": "Management information for oversight. Figures derive from platform state and audit trail (demo / operational data).",
    }


async def build_eco_dashboard_payload(user: Dict[str, Any], *, pg: Optional[PostgresClient]) -> Dict[str, Any]:
    alerts = mi_scope_alerts(user)
    dashboard = _alerts_dashboard_payload(user if user_has_full_data_access(user) else user)
    by_analyst = _open_cases_by_analyst(alerts)
    sa = _sanctions_adverse_counts(alerts)

    ftr_lag: Optional[float] = None
    ftr_draft = 0
    if pg is not None:
        try:
            rows, _ = await list_ftrs(pg, limit=100, skip=0, status="DRAFT")
            ftr_draft = len(rows)
            lags: List[float] = []
            for row in rows:
                vd = row.get("value_date")
                fd = row.get("filing_deadline")
                if vd and fd:
                    try:
                        if hasattr(vd, "isoformat") and hasattr(fd, "isoformat"):
                            delta = (fd - vd).days if fd >= vd else 0
                            lags.append(float(delta))
                    except Exception:
                        pass
            if lags:
                ftr_lag = round(sum(lags) / len(lags), 2)
        except Exception:
            pass

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "refresh_interval_seconds": 300,
        "audience": "executive_compliance_officer",
        "operational": {
            "open_cases_by_analyst": by_analyst,
            "average_resolution_time_hours": dashboard.get("average_resolution_time_hours"),
            "pending_cco_str_approvals": dashboard.get("pending_cco_str_approvals", 0),
            "pending_cco_otc_approvals": dashboard.get("pending_cco_otc_approvals", 0),
            "ftr_filing_lag_avg_days_value_to_deadline": ftr_lag,
            "ftr_drafts_pending": ftr_draft,
            "sanctions_hits_flagged": sa["sanctions_hits_flagged"],
            "adverse_media_flags": sa["adverse_media_flags"],
            "counts_by_status": dashboard.get("counts_by_status"),
            "outcome_summary": dashboard.get("outcome_summary"),
        },
    }


def build_management_exceptions_payload(user: Dict[str, Any]) -> Dict[str, Any]:
    alerts = mi_scope_alerts(user)
    dashboard = _alerts_dashboard_payload(user if user_has_full_data_access(user) else user)
    sla_hours = 168.0
    breaches: List[Dict[str, Any]] = []
    now = datetime.utcnow()
    for a in alerts:
        if (a.status or "").lower() == "closed":
            continue
        ca = a.created_at
        if not isinstance(ca, datetime):
            continue
        age_h = (now - ca).total_seconds() / 3600.0
        if age_h > sla_hours:
            breaches.append(
                {
                    "alert_id": a.id,
                    "customer_id": a.customer_id,
                    "age_hours": round(age_h, 2),
                    "status": a.status,
                    "summary": (a.summary or "")[:200],
                }
            )

    pending_cco: List[Dict[str, Any]] = []
    for a in alerts:
        st = (a.status or "").lower()
        if st != "escalated":
            continue
        if a.cco_str_approved and not (a.otc_outcome == "true_positive" and not getattr(a, "cco_otc_approved", False)):
            continue
        need_str = not a.cco_str_approved and getattr(a, "otc_report_kind", None) != "otc_estr"
        need_otc = (
            (a.otc_outcome or "") == "true_positive"
            and bool(getattr(a, "otc_report_kind", None))
            and not bool(getattr(a, "cco_otc_approved", False))
        )
        if need_str or need_otc:
            pending_cco.append(
                {
                    "alert_id": a.id,
                    "customer_id": a.customer_id,
                    "needs_cco_str": need_str,
                    "needs_cco_otc": need_otc,
                    "summary": (a.summary or "")[:200],
                }
            )

    integrations = {
        "kafka": "unknown",
        "redis": "unknown",
        "postgres": "unknown",
        "note": "Attach live health probes in production; placeholder for MI narrative.",
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audience": "senior_management",
        "sla_breach_hours": sla_hours,
        "alerts_exceeding_sla": sorted(breaches, key=lambda x: -x["age_hours"])[:100],
        "cco_pending_escalations": pending_cco[:100],
        "failed_integrations": integrations,
        "summary_counts": {
            "sla_breaches": len(breaches),
            "cco_pending": len(pending_cco),
            "pending_cco_str_approvals": dashboard.get("pending_cco_str_approvals", 0),
        },
    }
