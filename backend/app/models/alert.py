from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


def _validate_alert_notification_action(
    action: str,
    *,
    investigator_id: Optional[str] = None,
    resolution: Optional[str] = None,
    resolution_notes: Optional[str] = None,
    escalate_reason: Optional[str] = None,
    escalated_to: Optional[str] = None,
) -> None:
    if action == "investigate":
        if not (investigator_id or "").strip():
            raise ValueError("investigator_id is required when action is investigate")
    elif action == "resolve":
        if not (resolution or "").strip():
            raise ValueError("resolution is required when action is resolve")
        if not (resolution_notes or "").strip():
            raise ValueError("resolution_notes is required when action is resolve")
    elif action == "escalate":
        if not (escalate_reason or "").strip():
            raise ValueError("escalate_reason is required when action is escalate")
        if not (escalated_to or "").strip():
            raise ValueError("escalated_to is required when action is escalate")


class AlertCreate(BaseModel):
    transaction_id: str
    customer_id: str
    severity: float = Field(ge=0, le=1)
    status: str = "open"
    rule_ids: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class InvestigationRequest(BaseModel):
    investigator_id: str
    notes: Optional[str] = None


class ResolutionRequest(BaseModel):
    """Close alert as non-suspicious after review. STR is not available; SAR (suspicious activity) generation is eligible in the demo workflow."""

    resolution: Literal["false_positive"]
    notes: str
    action_taken: Optional[str] = None


class EscalationRequest(BaseModel):
    """Escalate for senior review. True positive or CCO-review paths require CCO approval before STR generation."""

    escalated_to: str
    escalation_type: Literal["true_positive", "cco_review"] = "cco_review"
    reason: str = ""

    @model_validator(mode="after")
    def validate_escalation_fields(self) -> "EscalationRequest":
        if self.escalation_type == "cco_review" and not self.reason.strip():
            raise ValueError("Reason is required when escalation type is CCO review.")
        if not self.escalated_to.strip():
            raise ValueError("escalated_to is required.")
        return self


class CcoStrApprovalBody(BaseModel):
    notes: Optional[str] = Field(None, description="Optional notes recorded with CCO approval.")


class CcoRejectBody(BaseModel):
    """Chief Compliance Officer rejects an alert; compliance officer is notified (dashboard + email when configured)."""

    reason: str = Field(..., min_length=3, max_length=16000, description="Required rationale shown to the compliance officer.")


# Over-the-counter (OTC) regulatory filing — CO assessment, CCO approval, then ESTR or OTC-linked SAR (ESAR path).
OTC_FILING_REASONS = frozenset(
    {
        "regulatory_obligation",
        "internal_policy",
        "branch_referral",
        "customer_request",
        "supervisory_request",
        "other",
    }
)
OTC_SUBJECTS_ESTR = frozenset({"cash_deposit", "cash_withdrawal"})
OTC_SUBJECTS_ESAR = frozenset(
    {
        "change_of_name",
        "arrangement_of_name",
        "nin_update",
        "bvn_partial_name_change",
        "full_name_change",
        "dob_update",
        "name_and_dob_update",
    }
)
OTC_ALL_SUBJECTS = OTC_SUBJECTS_ESTR | OTC_SUBJECTS_ESAR


def otc_report_kind_for_subject(subject: str) -> str:
    s = (subject or "").strip()
    if s in OTC_SUBJECTS_ESTR:
        return "otc_estr"
    if s in OTC_SUBJECTS_ESAR:
        return "otc_esar"
    raise ValueError(f"Unknown OTC subject: {subject}")


class OtcReportSubmission(BaseModel):
    """Compliance officer OTC assessment: outcome drives whether CCO approval and report generation apply."""

    filing_reason: str = Field(..., min_length=3, max_length=128)
    filing_reason_detail: Optional[str] = Field(None, max_length=2000)
    outcome: Literal["false_positive", "true_positive"]
    subject: str = Field(..., min_length=3, max_length=128)
    officer_rationale: str = Field("", max_length=16000)

    @field_validator("filing_reason")
    @classmethod
    def normalize_filing_reason(cls, v: str) -> str:
        s = v.strip()
        if s not in OTC_FILING_REASONS:
            raise ValueError(f"filing_reason must be one of: {', '.join(sorted(OTC_FILING_REASONS))}")
        return s

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, v: str) -> str:
        s = v.strip()
        if s not in OTC_ALL_SUBJECTS:
            raise ValueError("subject is not a recognised OTC matter (cash vs identity-change categories).")
        return s

    @model_validator(mode="after")
    def validate_otc(self) -> "OtcReportSubmission":
        if self.outcome == "true_positive" and not str(self.officer_rationale or "").strip():
            raise ValueError("officer_rationale is required when outcome is true_positive.")
        if self.filing_reason == "other" and not (self.filing_reason_detail or "").strip():
            raise ValueError("filing_reason_detail is required when filing_reason is other.")
        return self


class CcoOtcApprovalBody(BaseModel):
    notes: Optional[str] = Field(None, description="Optional notes recorded with CCO approval for OTC filing.")


class EddNotificationRequest(BaseModel):
    """Customer EDD email. Optional compliance_action adds the same contextual fields as CCO notifications."""

    customer_email: str
    customer_name: str | None = None
    compliance_action: Literal["investigate", "resolve", "escalate"] | None = None
    investigator_id: str | None = None
    investigation_notes: str | None = None
    resolution: str | None = None
    resolution_notes: str | None = None
    escalate_reason: str | None = None
    escalated_to: str | None = None
    additional_note: str | None = None

    @model_validator(mode="after")
    def validate_compliance_action(self):
        if self.compliance_action is None:
            return self
        _validate_alert_notification_action(
            self.compliance_action,
            investigator_id=self.investigator_id,
            resolution=self.resolution,
            resolution_notes=self.resolution_notes,
            escalate_reason=self.escalate_reason,
            escalated_to=self.escalated_to,
        )
        return self


class CcoActionNotificationRequest(BaseModel):
    """Email to CCO (and optional extra recipients) describing the compliance action taken."""

    action: Literal["investigate", "resolve", "escalate"]
    investigator_id: str | None = None
    investigation_notes: str | None = None
    resolution: str | None = None  # true_positive | false_positive when action is resolve
    resolution_notes: str | None = None
    escalate_reason: str | None = None
    escalated_to: str | None = None
    additional_note: str | None = None
    extra_recipients: List[EmailStr] = Field(
        default_factory=list,
        description="Optional extra To: addresses (e.g. escalate target email).",
    )

    @model_validator(mode="after")
    def validate_action_fields(self):
        _validate_alert_notification_action(
            self.action,
            investigator_id=self.investigator_id,
            resolution=self.resolution,
            resolution_notes=self.resolution_notes,
            escalate_reason=self.escalate_reason,
            escalated_to=self.escalated_to,
        )
        return self


class AlertResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    transaction_id: str
    customer_id: str
    customer_name: Optional[str] = None
    severity: float
    status: str
    rule_ids: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    last_resolution: Optional[str] = Field(
        default=None,
        description="Resolution when status is closed (false_positive only in current workflow).",
    )
    cco_str_approved: bool = Field(
        default=False,
        description="After escalation, CCO must approve before STR generation.",
    )
    cco_str_rejected: bool = Field(
        default=False,
        description="Set when CCO rejects the alert (status becomes rejected); aligns with aml_alerts.cco_str_rejected.",
    )
    cco_str_rejection_reason: Optional[str] = Field(
        default=None,
        description="CCO rejection rationale (also echoed in investigation_history as action cco_reject).",
    )
    escalated_to_cco: bool = Field(
        default=False,
        description="True once compliance escalates to CCO track; cleared on resolve/reset.",
    )
    escalation_classification: Optional[str] = Field(
        default=None,
        description="When escalated: true_positive | cco_review.",
    )
    escalation_reason_notes: Optional[str] = Field(
        default=None,
        description="Compliance officer reason for escalation (CCO review or true-positive context).",
    )
    investigation_history: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    otc_filing_reason: Optional[str] = Field(default=None, description="Why the OTC return is being filed (CO).")
    otc_filing_reason_detail: Optional[str] = Field(default=None, description="Free text when filing_reason is other.")
    otc_outcome: Optional[Literal["false_positive", "true_positive"]] = Field(
        default=None,
        description="CO outcome: false positive ends OTC regulatory path; true positive awaits CCO then ESTR/ESAR.",
    )
    otc_subject: Optional[str] = Field(default=None, description="Matter subject (cash vs identity change).")
    otc_officer_rationale: Optional[str] = Field(default=None, description="Supporting rationale when true positive.")
    otc_report_kind: Optional[Literal["otc_estr", "otc_esar"]] = Field(
        default=None,
        description="Derived from subject when true positive: cash → otc_estr; identity changes → otc_esar.",
    )
    cco_otc_approved: bool = Field(
        default=False,
        description="After true-positive OTC, CCO must approve before ESTR or OTC ESAR generation.",
    )
    cco_estr_word_approved: bool = Field(
        default=False,
        description="Legacy flag; OTC ESTR drafting no longer gated on this in the demo app.",
    )
    otc_submitted_at: Optional[datetime] = Field(default=None)
    linked_transaction_type: Optional[str] = Field(
        default=None,
        description="Linked transaction type from the transaction store (list/search enrichment).",
    )
    linked_channel: Optional[str] = Field(
        default=None,
        description="Linked transaction channel from metadata (e.g. pos_terminal, atm, ussd, nibss_nip).",
    )
    walk_in_otc: bool = Field(
        default=False,
        description="True when linked txn metadata indicates OTC branch / walk-in capture.",
    )
    deleted_at: Optional[datetime] = Field(
        default=None,
        description="Soft-delete timestamp (retention / NDPA workflow); hidden from default API lists.",
    )
    primary_account_number: Optional[str] = Field(
        default=None,
        description="Primary account number for the grouped suspicious activity context (used for STR narrative focus).",
    )
    linked_accounts_count: int = Field(
        default=0,
        description="How many customer accounts (same BVN/ID) are linked to this alert context.",
    )
    linked_accounts: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="BVN/ID-linked customer accounts included in this alert context.",
    )
    related_transactions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Related transactions across linked accounts involved in suspicious activity context.",
    )


class CoNotificationMarkReadBody(BaseModel):
    """Mark CCO→CO inbox notifications as read (empty list = mark all for current user)."""

    notification_ids: Optional[List[str]] = Field(
        default=None,
        description="If null or omitted, all notifications for the signed-in user's email are marked read.",
    )


class AlertFilter(BaseModel):
    severity: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

