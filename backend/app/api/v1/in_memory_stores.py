"""Shared in-memory transaction and alert stores (avoids alerts ↔ transactions import cycle)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models.alert import AlertResponse
from app.models.transaction import TransactionResponse

_TXNS: Dict[str, TransactionResponse] = {}
_ALERTS: Dict[str, AlertResponse] = {}

# Compliance-officer workbench messages (e.g. CCO rejection); keyed by recipient email.
_CO_ACTION_NOTIFICATIONS: List[Dict[str, Any]] = []
_MAX_CO_NOTIFICATIONS = 400


def push_co_notification(entry: Dict[str, Any]) -> None:
    _CO_ACTION_NOTIFICATIONS.insert(0, entry)
    while len(_CO_ACTION_NOTIFICATIONS) > _MAX_CO_NOTIFICATIONS:
        _CO_ACTION_NOTIFICATIONS.pop()


def co_notifications_for_email(email: str, *, unread_only: bool = False) -> List[Dict[str, Any]]:
    e = (email or "").strip().lower()
    if not e:
        return []
    out = [n for n in _CO_ACTION_NOTIFICATIONS if str(n.get("recipient_email") or "").strip().lower() == e]
    if unread_only:
        out = [n for n in out if not n.get("read")]
    return out


def mark_co_notifications_read(email: str, notification_ids: Optional[List[str]] = None) -> int:
    """Mark notifications read for this recipient; if ids is None, mark all for that email."""
    e = (email or "").strip().lower()
    if not e:
        return 0
    want = {str(i).strip() for i in (notification_ids or []) if str(i).strip()}
    n_marked = 0
    for n in _CO_ACTION_NOTIFICATIONS:
        if str(n.get("recipient_email") or "").strip().lower() != e:
            continue
        if want and str(n.get("id") or "") not in want:
            continue
        if not n.get("read"):
            n["read"] = True
            n_marked += 1
    return n_marked
