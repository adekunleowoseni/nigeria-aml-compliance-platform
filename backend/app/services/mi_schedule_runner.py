"""Cron evaluation and email dispatch for MI schedules (runs inside API process)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from croniter import croniter as croniter_cls

from app.api.v1.reports import _REPORTS
from app.db.postgres_client import PostgresClient
from app.services import audit_trail
from app.services.board_pack_pdf import build_board_pack_pdf_bytes
from app.services.mail_notify import send_email_with_attachment, _smtp_configured
from app.services.mi_executive_service import (
    build_board_pack_payload,
    build_eco_dashboard_payload,
    build_management_exceptions_payload,
)
from app.services.mi_report_schedules_db import list_schedules, touch_fired

MI_SYSTEM_USER: Dict[str, Any] = {
    "role": "admin",
    "sub": "mi-scheduler",
    "email": "mi-scheduler@internal",
    "display_name": "MI Scheduler",
}


def _parse_last_fired(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _cron_fire_simple(cron_expression: str, last_fired_at: Optional[datetime], now: datetime) -> bool:
    """Fire if previous scheduled occurrence is after last_fired_at and within the last 5 minutes."""
    expr = (cron_expression or "").strip()
    if not expr:
        return False
    try:
        prev = croniter_cls(expr, now).get_prev(datetime)
    except Exception:
        return False
    if (now - prev).total_seconds() > 300:
        return False
    lf = last_fired_at
    if lf is None:
        return False
    return prev > lf


async def dispatch_one_schedule(
    pg: PostgresClient,
    row: Dict[str, Any],
    *,
    actor_email: str = "mi-scheduler@internal",
) -> Dict[str, Any]:
    rt = str(row.get("report_type") or "")
    sid = str(row.get("id") or "")
    recips = row.get("recipients") or []
    if isinstance(recips, str):
        try:
            recips = json.loads(recips)
        except Exception:
            recips = []
    emails = [str(x).strip() for x in recips if str(x).strip() and "@" in str(x)]
    if not emails:
        return {"schedule_id": sid, "skipped": True, "reason": "no_recipients"}

    if not _smtp_configured():
        audit_trail.record_event(
            action="mi_report.email_skipped",
            resource_type="mi_schedule",
            resource_id=sid,
            actor_sub="mi-scheduler",
            actor_email=actor_email,
            actor_role="system",
            details={"report_type": rt, "reason": "smtp_not_configured"},
        )
        return {"schedule_id": sid, "skipped": True, "reason": "smtp_not_configured"}

    attachments: List[tuple[str, bytes, str]] = []
    subject = ""
    body = ""

    if rt == "board_aml_pack":
        payload = await build_board_pack_payload(MI_SYSTEM_USER, pg=pg, _reports=_REPORTS)
        try:
            title_path = Path(__file__).resolve().parent.parent.parent / "templates" / "reports" / "board_pack_title.txt"
            if title_path.is_file():
                payload["template_title"] = title_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        pdf = build_board_pack_pdf_bytes(payload)
        attachments.append(("Board_AML_Pack.pdf", pdf, "application/pdf"))
        subject = "Board AML MI Pack (scheduled)"
        body = (
            f"Please find the Board AML pack attached.\n"
            f"Material escalations: {payload.get('kpi', {}).get('material_escalations_count', '—')}\n"
            f"STR submitted (in-memory): {payload.get('kpi', {}).get('str_filed_submitted', '—')}\n"
        )
    elif rt == "eco_dashboard":
        payload = await build_eco_dashboard_payload(MI_SYSTEM_USER, pg=pg)
        raw = json.dumps(payload, indent=2, default=str).encode("utf-8")
        attachments.append(("ECO_Dashboard.json", raw, "application/json"))
        subject = "ECO operational dashboard (scheduled)"
        body = "ECO dashboard JSON snapshot attached."
    elif rt == "management_exceptions":
        payload = build_management_exceptions_payload(MI_SYSTEM_USER)
        raw = json.dumps(payload, indent=2, default=str).encode("utf-8")
        attachments.append(("Management_Exceptions.json", raw, "application/json"))
        subject = "Management exception report (scheduled)"
        body = "Management exceptions JSON snapshot attached."
    else:
        return {"schedule_id": sid, "skipped": True, "reason": "unknown_type"}

    await send_email_with_attachment(emails, subject, body, attachments)
    await touch_fired(pg, sid)
    audit_trail.record_event(
        action="mi_report.email_dispatched",
        resource_type="mi_schedule",
        resource_id=sid,
        actor_sub="mi-scheduler",
        actor_email=actor_email,
        actor_role="system",
        details={
            "report_type": rt,
            "recipient_count": len(emails),
            "attachments": [a[0] for a in attachments],
        },
    )
    return {"schedule_id": sid, "sent": True, "recipients": len(emails)}


async def run_due_mi_schedules(pg: PostgresClient, *, actor_email: str = "mi-scheduler@internal") -> Dict[str, Any]:
    now = datetime.utcnow()
    rows = await list_schedules(pg)
    results: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("is_paused"):
            continue
        lf = _parse_last_fired(row.get("last_fired_at"))
        if not _cron_fire_simple(str(row.get("cron_expression") or ""), lf, now):
            continue
        results.append(await dispatch_one_schedule(pg, row, actor_email=actor_email))
    return {"at": now.isoformat() + "Z", "results": results}
