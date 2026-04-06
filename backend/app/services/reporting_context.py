"""Merge institution reporting profile into goAML-style payloads; calendar preview helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from croniter import croniter as croniter_cls

from app.services.reporting_profile_db import DEFAULT_OUTPUTS

# CBN-first presets; RC numbers for banks are illustrative placeholders — admins should edit in Settings.
TEMPLATE_PACK_PRESETS: Dict[str, Dict[str, str]] = {
    "cbn_default": {
        "institution_display_name": "Licensed Financial Institution",
        "reporting_entity_name": "Licensed Financial Institution (CBN / NFIU regulatory returns)",
        "entity_registration_ref": "CBN-FI-________",
    },
    "gtbank": {
        "institution_display_name": "Guaranty Trust Bank PLC",
        "reporting_entity_name": "Guaranty Trust Bank PLC",
        "entity_registration_ref": "RC 152321",
    },
    "zenith": {
        "institution_display_name": "Zenith Bank PLC",
        "reporting_entity_name": "Zenith Bank PLC",
        "entity_registration_ref": "RC 150597",
    },
    "uba": {
        "institution_display_name": "United Bank for Africa PLC",
        "reporting_entity_name": "United Bank for Africa PLC",
        "entity_registration_ref": "RC-UBA-________",
    },
    "access": {
        "institution_display_name": "Access Bank PLC",
        "reporting_entity_name": "Access Bank PLC",
        "entity_registration_ref": "RC-ACCESS-________",
    },
}


def merge_goaml_stub_payload(profile: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload)
    if not profile:
        p.setdefault("entity_name", "Demo Reporting Entity")
        p.setdefault("entity_rc", "RC-000000")
        return p
    p.setdefault("entity_name", profile.get("reporting_entity_name") or "Demo Reporting Entity")
    p.setdefault("entity_rc", profile.get("entity_registration_ref") or "RC-000000")
    if profile.get("institution_display_name"):
        p.setdefault("institution_display_name", profile["institution_display_name"])
    if profile.get("template_pack"):
        p.setdefault("template_pack", profile["template_pack"])
    if profile.get("narrative_style"):
        p.setdefault("narrative_style", profile["narrative_style"])
    return p


def reporting_entity_for_str_xml(profile: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not profile:
        return {"name": "Demo Reporting Entity", "registration_number": "RC-000000"}
    return {
        "name": str(profile.get("reporting_entity_name") or "Demo Reporting Entity"),
        "registration_number": str(profile.get("entity_registration_ref") or "RC-000000"),
    }


def effective_default_outputs(stored: Any) -> Dict[str, Any]:
    base = dict(DEFAULT_OUTPUTS)
    if isinstance(stored, dict):
        base.update(stored)
    return base


def _next_monthly_dates(day_of_month: int, count: int = 3) -> List[date]:
    today = date.today()
    dom = max(1, min(int(day_of_month or 1), 28))
    out: List[date] = []
    y, m = today.year, today.month
    for _ in range(count * 14):
        try:
            d = date(y, m, dom)
        except ValueError:
            d = date(y, m, 28)
        if d >= today and d not in out:
            out.append(d)
            if len(out) >= count:
                break
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _next_weekly_dates(day_of_week: int, count: int = 3) -> List[date]:
    """day_of_week: 0=Monday .. 6=Sunday"""
    today = date.today()
    target = int(day_of_week) % 7
    out: List[date] = []
    for i in range(60):
        d = today + timedelta(days=i)
        if d.weekday() == target:
            out.append(d)
            if len(out) >= count:
                break
    return out


def upcoming_calendar_preview(entries: List[Dict[str, Any]], *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Lightweight next due hints for admin UI (not a substitute for compliance calendar software)."""
    now = now or datetime.utcnow()
    today = now.date()
    previews: List[Dict[str, Any]] = []
    for e in entries:
        if not e.get("enabled", True):
            continue
        freq = str(e.get("frequency") or "").lower()
        dates: List[date] = []
        if freq == "daily":
            dates = [today + timedelta(days=i) for i in range(3)]
        elif freq == "weekly":
            dow = e.get("day_of_week")
            if dow is not None:
                dates = _next_weekly_dates(int(dow), 3)
        elif freq == "monthly":
            dom = e.get("day_of_month") or 1
            dates = _next_monthly_dates(int(dom), 3)
        elif freq == "quarterly":
            dates = [today + timedelta(days=30 * i) for i in (0, 1, 2)]
        elif freq == "annual":
            dates = [today + timedelta(days=365 * i) for i in (0, 1)]
        elif freq == "cron" and (e.get("cron_expression") or "").strip():
            try:
                it = croniter_cls(str(e["cron_expression"]).strip(), now)
                for _ in range(3):
                    nxt = it.get_next(datetime)
                    dates.append(nxt.date())
            except Exception:
                dates = []
        off = int(e.get("submission_offset_days") or 0)
        previews.append(
            {
                "id": e.get("id"),
                "slug": e.get("slug"),
                "title": e.get("title"),
                "report_family": e.get("report_family"),
                "frequency": freq,
                "next_period_dates": [d.isoformat() for d in dates[:3]],
                "submission_offset_days": off,
                "reminder_days_before": e.get("reminder_days_before"),
            }
        )
    return previews
