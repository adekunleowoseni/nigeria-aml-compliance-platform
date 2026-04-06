from __future__ import annotations

import asyncio
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional, Tuple

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


def _send_sync_with_attachments(
    to_addrs: List[str],
    subject: str,
    body: str,
    attachments: List[Tuple[str, bytes, str]],
) -> None:
    """attachments: (filename, content, maintype/subtype e.g. application/pdf)."""
    if not _smtp_configured():
        raise RuntimeError("SMTP is not configured (set SMTP_HOST and SMTP_FROM_EMAIL).")
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for filename, content, mime in attachments:
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        if not subtype:
            subtype = "octet-stream"
        part = MIMEBase(maintype, subtype)
        part.set_payload(content)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from_email, to_addrs, msg.as_string())


async def send_email_with_attachment(
    to_addrs: List[str],
    subject: str,
    body: str,
    attachments: List[Tuple[str, bytes, str]],
) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: _send_sync_with_attachments(to_addrs, subject, body, attachments))


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


def build_cco_str_approval_required_email(
    *,
    cco_name_or_role: str,
    alert_id: str,
    customer_id: str,
    transaction_id: str,
    summary: str,
    analyst: str,
    escalation_type: str,
    reason: str,
    escalated_to: str,
) -> tuple[str, str]:
    """Notify CCO that an alert was escalated and STR filing awaits their approval in the platform."""
    et_label = "Confirmed suspicious (true positive)" if escalation_type == "true_positive" else "CCO review referral"
    subject = f"AML: STR pre-approval required — {alert_id[:8]}… ({et_label})"
    body = (
        f"Dear {cco_name_or_role},\n\n"
        f"An alert has been escalated and requires your approval before compliance can generate a Suspicious "
        f"Activity Report (STR) in the platform.\n\n"
        f"Alert ID: {alert_id}\n"
        f"Customer: {customer_id}\n"
        f"Transaction: {transaction_id}\n"
        f"Summary: {summary}\n"
        f"Escalation type: {et_label}\n"
        f"Reason / context: {reason or '—'}\n"
        f"Escalated to (line responsibility): {escalated_to}\n"
        f"Submitted by: {analyst}\n\n"
        f"Please open the CCO Review queue in the AML dashboard, review the case, and select Approve for STR "
        f"when policy and NFIU timelines support filing.\n"
    )
    return subject, body


def build_co_cco_rejection_email(
    *,
    officer_greeting: str,
    alert_id: str,
    customer_id: str,
    transaction_id: str,
    summary: str,
    cco_name: str,
    rejection_reason: str,
) -> tuple[str, str]:
    """Notify the compliance officer that the CCO rejected the alert / escalation."""
    subject = f"AML: Alert rejected by CCO — {alert_id[:8]}…"
    body = (
        f"Dear {officer_greeting},\n\n"
        f"The Chief Compliance Officer has rejected the following alert. "
        f"Please review the reason below and take appropriate next steps in the AML platform.\n\n"
        f"Alert ID: {alert_id}\n"
        f"Customer: {customer_id}\n"
        f"Transaction: {transaction_id}\n"
        f"Summary: {summary or '—'}\n\n"
        f"CCO: {cco_name}\n"
        f"Rejection reason:\n{rejection_reason.strip()}\n\n"
        f"— Automated message from Nigeria AML Compliance Platform\n"
    )
    return subject, body


def build_cco_otc_approval_required_email(
    *,
    cco_name_or_role: str,
    alert_id: str,
    customer_id: str,
    transaction_id: str,
    summary: str,
    analyst: str,
    otc_subject: str,
    otc_report_kind: str,
    officer_rationale: str,
) -> tuple[str, str]:
    """Notify CCO that a compliance officer filed a true-positive OTC matter pending approval."""
    kind_label = "OTC ESTR (cash)" if otc_report_kind == "otc_estr" else "OTC ESAR (identity change)"
    subject = f"AML: OTC filing pre-approval — {alert_id[:8]}… ({kind_label})"
    body = (
        f"Dear {cco_name_or_role},\n\n"
        f"A compliance officer has submitted an over-the-counter (OTC) regulatory assessment as "
        f"true positive. Your approval is required before {kind_label} can be generated in the platform.\n\n"
        f"Alert ID: {alert_id}\n"
        f"Customer: {customer_id}\n"
        f"Transaction: {transaction_id}\n"
        f"Summary: {summary}\n"
        f"OTC subject (matter): {otc_subject}\n"
        f"Officer rationale: {officer_rationale or '—'}\n"
        f"Submitted by: {analyst}\n\n"
        f"Please open CCO review in the AML dashboard, approve the OTC filing when appropriate, then "
        f"compliance can generate the report from Regulatory reports.\n"
    )
    return subject, body


def build_lea_cco_approval_request_email(
    *,
    cco_name_or_role: str,
    request_id: str,
    agency: str,
    customer_id: str,
    period_start: str,
    period_end: str,
    recipient_email: str,
    include_aop: bool,
    analyst: str,
    internal_notes: str,
    requester_ip: str = "",
    client_public_ip: str = "",
) -> tuple[str, str]:
    subject = f"AML: LEA disclosure approval — {agency} / {customer_id[:32]}"
    notes = (internal_notes or "").strip() or "—"
    rip = (requester_ip or "").strip() or "—"
    pip = (client_public_ip or "").strip() or "—"
    body = (
        f"Dear {cco_name_or_role},\n\n"
        f"A compliance officer has prepared a law-enforcement agency (LEA) information package and requests "
        f"your approval before it may be transmitted.\n\n"
        f"Request ID: {request_id}\n"
        f"Agency: {agency}\n"
        f"Customer ID: {customer_id}\n"
        f"Statement period (filter): {period_start} to {period_end}\n"
        f"Intended recipient email: {recipient_email}\n"
        f"Include AOP draft: {'yes' if include_aop else 'no'}\n"
        f"Prepared by: {analyst}\n"
        f"Request IP (server / proxy): {rip}\n"
        f"Public IP (browser self-detected): {pip}\n"
        f"Internal notes: {notes}\n\n"
        f"Please sign in as CCO or Administrator, open Regulatory reports → LEA Request, and approve request "
        f"{request_id[:8]}… when due diligence is satisfied. The officer may send the package only after approval.\n"
    )
    return subject, body


def build_lea_package_email(
    *,
    agency: str,
    customer_id: str,
    period_start: str,
    period_end: str,
    statement_text: str,
    aop_report_id: str | None,
    requester_ip: str,
    workstation_mac: str,
    prepared_by: str,
    bank_reference: str,
    client_public_ip: str = "",
) -> tuple[str, str]:
    subject = f"Customer information package — {agency} — Ref {bank_reference[:12]}"
    mac = (workstation_mac or "").strip() or "Not provided (workstation identifier)"
    aop_line = f"AOP draft report ID (goAML stub): {aop_report_id}\n" if aop_report_id else "AOP: not included.\n"
    body = (
        f"Law enforcement colleagues,\n\n"
        f"Please find below the account activity extract and related identifiers for your request.\n"
        f"This transmission is sent under internal compliance approval.\n\n"
        f"Agency: {agency}\n"
        f"Customer ID: {customer_id}\n"
        f"Activity period: {period_start} to {period_end}\n"
        f"Prepared by: {prepared_by}\n"
        f"Bank reference: {bank_reference}\n"
        f"Originating request IP (server-recorded): {requester_ip or '—'}\n"
        f"Public IP (browser self-detected): {(client_public_ip or '').strip() or '—'}\n"
        f"Workstation / asset identifier (as declared; MAC not available in browsers): {mac}\n"
        f"{aop_line}\n"
        f"--- Statement of account (demo extract) ---\n"
        f"{statement_text}\n"
        f"--- End ---\n"
    )
    return subject, body
