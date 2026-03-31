from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from app.config import settings
from app.core.logging import get_logger

log = get_logger(component="mail_notify")


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from_email)


def _send_sync(to_addrs: List[str], subject: str, body: str) -> None:
    if not _smtp_configured():
        raise RuntimeError("SMTP is not configured (set SMTP_HOST and SMTP_FROM_EMAIL).")
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from_email, to_addrs, msg.as_string())


async def send_plain_email(to_addrs: List[str], subject: str, body: str) -> None:
    """Send email via SMTP in a thread (non-blocking for async handlers)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: _send_sync(to_addrs, subject, body))


def _edd_customer_compliance_context(
    *,
    compliance_action: str,
    investigator_id: Optional[str] = None,
    investigation_notes: Optional[str] = None,
    resolution: Optional[str] = None,
    resolution_notes: Optional[str] = None,
    escalate_reason: Optional[str] = None,
    escalated_to: Optional[str] = None,
    additional_note: Optional[str] = None,
) -> str:
    """Plain-language paragraph(s) for the customer (no internal jargon beyond what you supply)."""
    lines: List[str] = [
        "For your awareness, this request is linked to our regulatory review of recent activity:",
        "",
    ]
    if compliance_action == "investigate":
        lines.append(f"• A compliance review is in progress (case reference: {investigator_id or '—'}).")
        if investigation_notes and investigation_notes.strip():
            lines.append(f"  Further detail: {investigation_notes.strip()}")
    elif compliance_action == "resolve":
        res_label = (
            "the review requires ongoing verification and the documentation below"
            if (resolution or "").strip() == "true_positive"
            else "the review is proceeding as a routine verification and we require the documentation below"
        )
        lines.append(f"• Outcome: {res_label}.")
        if resolution_notes and resolution_notes.strip():
            lines.append(f"  Summary: {resolution_notes.strip()}")
    elif compliance_action == "escalate":
        lines.append("• Your file has been referred for senior compliance review.")
        if escalate_reason and escalate_reason.strip():
            lines.append(f"  Reason: {escalate_reason.strip()}")
        if escalated_to and escalated_to.strip():
            lines.append(f"  Responsible party: {escalated_to.strip()}")
    lines.append("")
    if additional_note and additional_note.strip():
        lines.extend(["Additional information:", additional_note.strip(), ""])
    return "\n".join(lines)


def build_edd_request_email(
    *,
    customer_name: str,
    customer_email: str,
    alert_id: str,
    transaction_id: str,
    summary: str,
    requested_by: str,
    compliance_action: Optional[str] = None,
    investigator_id: Optional[str] = None,
    investigation_notes: Optional[str] = None,
    resolution: Optional[str] = None,
    resolution_notes: Optional[str] = None,
    escalate_reason: Optional[str] = None,
    escalated_to: Optional[str] = None,
    additional_note: Optional[str] = None,
) -> tuple[str, str]:
    subject = f"Enhanced Due Diligence (EDD) request — Alert {alert_id[:8]}…"
    context = ""
    if compliance_action:
        context = _edd_customer_compliance_context(
            compliance_action=compliance_action,
            investigator_id=investigator_id,
            investigation_notes=investigation_notes,
            resolution=resolution,
            resolution_notes=resolution_notes,
            escalate_reason=escalate_reason,
            escalated_to=escalated_to,
            additional_note=additional_note,
        )
    body = (
        f"Dear {customer_name},\n\n"
        f"Further to our regulatory obligations, we require additional information to complete "
        f"enhanced due diligence on recent account activity.\n\n"
        f"Reference: Alert {alert_id}\n"
        f"Transaction reference: {transaction_id}\n"
        f"Summary: {summary}\n\n"
        f"{context}"
        f"Please contact your relationship manager or reply to this message with the requested "
        f"documentation within the timeframe stated in your account terms.\n\n"
        f"— Compliance ({requested_by})\n"
    )
    return subject, body


def build_cco_pre_escalation_email(
    *,
    cco_name_or_role: str,
    alert_id: str,
    customer_id: str,
    transaction_id: str,
    summary: str,
    analyst: str,
    action: str,
) -> tuple[str, str]:
    subject = f"AML pre-escalation / STR review — Alert {alert_id[:8]}…"
    body = (
        f"Dear {cco_name_or_role},\n\n"
        f"This is an automated notification prior to final escalation or regulatory filing.\n\n"
        f"Alert ID: {alert_id}\n"
        f"Customer: {customer_id}\n"
        f"Transaction: {transaction_id}\n"
        f"Summary: {summary}\n"
        f"Prepared by: {analyst}\n"
        f"Next step: {action}\n\n"
        f"Please review in the AML platform and confirm alignment with internal policy and NFIU timelines.\n"
    )
    return subject, body


def build_cco_action_notification_email(
    *,
    cco_name_or_role: str,
    alert_id: str,
    customer_id: str,
    transaction_id: str,
    summary: str,
    analyst: str,
    action: str,
    investigator_id: Optional[str] = None,
    investigation_notes: Optional[str] = None,
    resolution: Optional[str] = None,
    resolution_notes: Optional[str] = None,
    escalate_reason: Optional[str] = None,
    escalated_to: Optional[str] = None,
    additional_note: Optional[str] = None,
) -> tuple[str, str]:
    action_label = {"investigate": "Under investigation", "resolve": "Resolved", "escalate": "Escalated"}.get(
        action, action
    )
    subject = f"AML alert — {action_label} — {alert_id[:8]}…"
    lines = [
        f"Dear {cco_name_or_role},",
        "",
        f"This notification records the following compliance action on alert {alert_id}.",
        "",
        f"Action: {action_label}",
        f"Alert ID: {alert_id}",
        f"Customer: {customer_id}",
        f"Transaction: {transaction_id}",
        f"Summary: {summary}",
        f"Notified by: {analyst}",
        "",
    ]
    if action == "investigate":
        lines.extend(
            [
                f"Investigator ID: {investigator_id or '—'}",
                f"Notes: {investigation_notes.strip() if investigation_notes else '—'}",
                "",
            ]
        )
    elif action == "resolve":
        lines.extend(
            [
                f"Resolution: {resolution or '—'}",
                f"Resolution notes: {resolution_notes or '—'}",
                "",
            ]
        )
    elif action == "escalate":
        lines.extend(
            [
                f"Reason: {escalate_reason or '—'}",
                f"Escalate to: {escalated_to or '—'}",
                "",
            ]
        )
    if additional_note and additional_note.strip():
        lines.extend(["Additional note:", additional_note.strip(), ""])
    lines.append("Please review in the AML platform as needed.")
    body = "\n".join(lines) + "\n"
    return subject, body
