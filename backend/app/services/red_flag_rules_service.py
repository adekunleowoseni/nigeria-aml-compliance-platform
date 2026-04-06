"""Evaluate admin-configured red-flag rules against live transaction + KYC text."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.db.postgres_client import PostgresClient
from app.services import red_flag_rules_db as rfdb
from app.services.typology_rules import TypologyHit

_RULES_CACHE: Optional[Tuple[List[Dict[str, Any]], float]] = None
_CACHE_TTL_SEC = 45.0


def invalidate_rules_cache() -> None:
    global _RULES_CACHE
    _RULES_CACHE = None


async def _get_cached_rules(pg: PostgresClient) -> List[Dict[str, Any]]:
    global _RULES_CACHE
    now = time.time()
    if _RULES_CACHE is not None and (now - _RULES_CACHE[1]) < _CACHE_TTL_SEC:
        return _RULES_CACHE[0]
    rows = await rfdb.list_rules(pg, enabled_only=True)
    _RULES_CACHE = (rows, now)
    return rows


def _build_haystack(
    txn: Dict[str, Any],
    *,
    customer_remarks: str = "",
    line_of_business: str = "",
) -> str:
    meta = txn.get("metadata") if isinstance(txn.get("metadata"), dict) else {}
    parts: List[str] = [
        str(txn.get("narrative") or ""),
        str(txn.get("remarks") or ""),
        customer_remarks or "",
        line_of_business or "",
        str(txn.get("counterparty_name") or meta.get("counterparty_name") or ""),
        str(txn.get("counterparty_id") or meta.get("counterparty_id") or ""),
        str(txn.get("transaction_type") or ""),
        str(meta.get("channel") or ""),
        str(meta.get("profile") or ""),
        str(meta.get("pattern") or ""),
    ]
    try:
        parts.append(json.dumps(meta, default=str))
    except Exception:
        parts.append(str(meta))
    return "\n".join(x for x in parts if x)


def _patterns_match(patterns: Sequence[str], haystack: str) -> bool:
    if not patterns:
        return False
    h = haystack
    hl = h.lower()
    for p in patterns:
        s = str(p).strip()
        if not s:
            continue
        if s.lower().startswith("regex:"):
            try:
                if re.search(s[6:].strip(), h, re.I | re.DOTALL):
                    return True
            except re.error:
                continue
            continue
        if s.lower() in hl:
            return True
    return False


def evaluate_red_flags_sync(rules: List[Dict[str, Any]], haystack: str) -> List[TypologyHit]:
    hits: List[TypologyHit] = []
    for row in rules:
        raw_pat = row.get("match_patterns")
        if isinstance(raw_pat, str):
            try:
                patterns = json.loads(raw_pat)
            except json.JSONDecodeError:
                patterns = []
        elif isinstance(raw_pat, list):
            patterns = raw_pat
        else:
            patterns = []
        patterns = [str(x) for x in patterns if str(x).strip()]
        if not _patterns_match(patterns, haystack):
            continue
        code = str(row.get("rule_code") or "custom")
        title = str(row.get("title") or code)
        desc = str(row.get("description") or "")
        hits.append(
            TypologyHit(
                rule_id=f"RF-{code}",
                title=title[:200],
                narrative=(desc[:900] if desc else title)[:900],
                nfiu_reference="Configurable red flag",
            )
        )
    return hits


async def evaluate_custom_red_flags(
    pg: Optional[PostgresClient],
    txn: Dict[str, Any],
    *,
    customer_remarks: str = "",
    line_of_business: str = "",
) -> List[TypologyHit]:
    if pg is None:
        return []
    try:
        rules = await _get_cached_rules(pg)
    except Exception:
        return []
    if not rules:
        return []
    haystack = _build_haystack(txn, customer_remarks=customer_remarks, line_of_business=line_of_business)
    return evaluate_red_flags_sync(rules, haystack)
