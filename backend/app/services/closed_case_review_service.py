"""
Closed case sampling, reviewer assignment (exclude original investigators), and alert re-open.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.models.alert import AlertResponse


def typology_pattern_choices() -> List[Dict[str, str]]:
    """Dropdown labels aligned with internal typology rule IDs (demo)."""
    return [
        {"id": "TYP-FIRST-HUGE", "label": "First-time huge transaction"},
        {"id": "TYP-SUDDEN-MOVEMENT", "label": "Sudden movement vs baseline"},
        {"id": "TYP-FAN-IN", "label": "Fan-in (aggregation)"},
        {"id": "TYP-FAN-OUT", "label": "Fan-out (distribution)"},
        {"id": "TYP-STRUCTURING", "label": "Structuring / smurfing"},
        {"id": "TYP-CORP-TO-INDIVIDUAL", "label": "Corporate to individual"},
        {"id": "TYP-GOV-FLOW", "label": "Government-related flow"},
        {"id": "TYP-PROFILE-MISMATCH", "label": "Profile vs narrative mismatch"},
        {"id": "TYP-EXPECTED-TURNOVER", "label": "Turnover vs expected profile"},
        {"id": "TYP-CRYPTO-KEYWORD", "label": "Crypto-related narrative"},
        {"id": "TYP-CHANNEL-HOP", "label": "Channel hopping"},
        {"id": "TYP-TRADE-PRICING", "label": "Trade mis-pricing"},
        {"id": "TYP-SENSITIVE-GOODS", "label": "Sensitive goods"},
        {"id": "TYP-TRAFFICKING-KEYWORD", "label": "Trafficking / exploitation wording"},
        {"id": "TYP-PEP", "label": "PEP exposure"},
        {"id": "TYP-SANCTIONS-JURISDICTION", "label": "Sanctions jurisdiction"},
        {"id": "OTHER", "label": "Other / not listed"},
    ]


def _parse_at(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def alert_closed_at_utc(a: AlertResponse) -> Optional[datetime]:
    """Best-effort close timestamp for closed alerts."""
    if (a.status or "").lower() != "closed":
        return None
    if a.updated_at:
        u = a.updated_at
        return u if u.tzinfo else u.replace(tzinfo=timezone.utc)
    for h in reversed(a.investigation_history or []):
        if not isinstance(h, dict):
            continue
        if (h.get("action") or "").lower() in ("resolve", "resolved", "close", "closed"):
            t = _parse_at(h.get("at"))
            if t:
                return t
    c = a.created_at
    if isinstance(c, datetime):
        return c if c.tzinfo else c.replace(tzinfo=timezone.utc)
    return None


def alert_in_period(a: AlertResponse, start: date, end: date) -> bool:
    t = alert_closed_at_utc(a)
    if not t:
        return False
    d = t.astimezone(timezone.utc).date()
    return start <= d <= end


def investigation_participant_emails(a: AlertResponse) -> Set[str]:
    """Emails / IDs declared in investigation history (lowercased)."""
    s: Set[str] = set()
    for h in a.investigation_history or []:
        if not isinstance(h, dict):
            continue
        for key in ("investigator_id", "approved_by", "escalated_to", "assigned_to", "notified_by", "by"):
            v = h.get(key)
            if v and str(v).strip():
                s.add(str(v).strip().lower())
    return s


def pick_reviewer_email(a: AlertResponse, analyst_pool: List[str]) -> str:
    """Random analyst not in original investigation participants; fallback if pool exhausted."""
    participants = investigation_participant_emails(a)
    clean = [e for e in analyst_pool if e.strip().lower() not in participants]
    pool = clean if clean else analyst_pool
    if not pool:
        return "unassigned@demo.local"
    return random.choice(pool)


def sample_size(n_candidates: int) -> int:
    """5% of closed cases, minimum 10, capped at population."""
    if n_candidates <= 0:
        return 0
    k = max(10, int(math.ceil(n_candidates * 0.05)))
    return min(k, n_candidates)


def filter_candidates(
    alerts: List[AlertResponse],
    period_start: date,
    period_end: date,
    sample_type: str,
) -> List[AlertResponse]:
    st = (sample_type or "RANDOM").strip().upper()
    closed = [a for a in alerts if (a.status or "").lower() == "closed" and alert_in_period(a, period_start, period_end)]
    if st == "ALL":
        return closed[:500]
    if st == "HIGH_RISK":
        return [a for a in closed if float(a.severity or 0) >= 0.65 or _has_typology(a)]
    return closed


def _has_typology(a: AlertResponse) -> bool:
    for rid in a.rule_ids or []:
        if str(rid).upper().startswith("TYP-"):
            return True
    return False


def sample_alerts(candidates: List[AlertResponse], sample_type: str) -> List[AlertResponse]:
    st = (sample_type or "RANDOM").strip().upper()
    if st == "ALL":
        return candidates
    k = sample_size(len(candidates))
    if k <= 0:
        return []
    if st == "HIGH_RISK":
        candidates = sorted(candidates, key=lambda x: float(x.severity or 0), reverse=True)
        return candidates[:k]
    shuffled = list(candidates)
    random.shuffle(shuffled)
    return shuffled[:k]


def previous_calendar_month(today: date) -> Tuple[date, date]:
    first_this = today.replace(day=1)
    end_prev = first_this - timedelta(days=1)
    start_prev = end_prev.replace(day=1)
    return start_prev, end_prev


async def reopen_closed_alert(original: AlertResponse, review_id: str) -> str:
    """Create a new open alert referencing the original (runtime store)."""
    from uuid import uuid4

    from app.services.aml_runtime_store import get_aml_runtime_store

    now = datetime.now(timezone.utc)
    new_id = str(uuid4())
    hist = [
        {
            "action": "reopen_from_periodic_review",
            "original_alert_id": original.id,
            "closed_case_review_id": review_id,
            "at": now.isoformat().replace("+00:00", "Z"),
        }
    ]
    summary_base = (original.summary or "Case re-opened from periodic review").strip()
    summary = f"[Re-opened] {summary_base}"[:500]
    na = original.model_copy(
        update={
            "id": new_id,
            "status": "open",
            "severity": min(0.95, max(float(original.severity or 0.5), 0.55)),
            "summary": summary,
            "last_resolution": None,
            "investigation_history": hist,
            "created_at": now,
            "updated_at": now,
            "cco_str_approved": False,
            "cco_str_rejected": False,
            "cco_str_rejection_reason": None,
            "cco_otc_approved": False,
            "otc_submitted_at": None,
        }
    )
    await get_aml_runtime_store().alert_put(na)
    return new_id
