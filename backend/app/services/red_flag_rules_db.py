"""Admin-configurable AML red-flag rules (Regulatory / internal typology library)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.db.postgres_client import PostgresClient

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$", re.I)


def validate_rule_code(code: str) -> str:
    c = (code or "").strip().lower().replace(" ", "_")
    if not _SLUG_RE.match(c):
        raise ValueError(
            "rule_code must be 1–128 chars: start with letter/number, then letters, numbers, underscore, hyphen"
        )
    return c


async def ensure_red_flag_rules_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS aml_red_flag_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_code TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            match_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


async def list_rules(pg: PostgresClient, *, enabled_only: bool = False) -> List[Dict[str, Any]]:
    if enabled_only:
        rows = await pg.fetch(
            "SELECT id, rule_code, title, description, enabled, match_patterns, updated_by, created_at, updated_at "
            "FROM aml_red_flag_rules WHERE enabled = TRUE ORDER BY title ASC"
        )
    else:
        rows = await pg.fetch(
            "SELECT id, rule_code, title, description, enabled, match_patterns, updated_by, created_at, updated_at "
            "FROM aml_red_flag_rules ORDER BY title ASC"
        )
    return [dict(r) for r in rows]


async def get_rule_by_code(pg: PostgresClient, rule_code: str) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow(
        "SELECT id, rule_code, title, description, enabled, match_patterns, updated_by, created_at, updated_at "
        "FROM aml_red_flag_rules WHERE rule_code = $1",
        rule_code,
    )
    return dict(row) if row else None


async def upsert_rule(
    pg: PostgresClient,
    *,
    rule_code: str,
    title: str,
    description: str,
    enabled: bool,
    match_patterns: List[str],
    updated_by: str,
) -> Dict[str, Any]:
    rc = validate_rule_code(rule_code)
    pat_json = json.dumps([str(p) for p in match_patterns if str(p).strip()], default=str)
    await pg.execute(
        """
        INSERT INTO aml_red_flag_rules (rule_code, title, description, enabled, match_patterns, updated_by, updated_at)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, NOW())
        ON CONFLICT (rule_code) DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            enabled = EXCLUDED.enabled,
            match_patterns = EXCLUDED.match_patterns,
            updated_by = EXCLUDED.updated_by,
            updated_at = NOW();
        """,
        rc,
        title[:500],
        description[:8000],
        bool(enabled),
        pat_json,
        (updated_by or "")[:500] or None,
    )
    row = await pg.fetchrow(
        "SELECT id, rule_code, title, description, enabled, match_patterns, updated_by, created_at, updated_at "
        "FROM aml_red_flag_rules WHERE rule_code = $1",
        rc,
    )
    return dict(row) if row else {}


async def delete_rule(pg: PostgresClient, rule_code: str) -> bool:
    rc = validate_rule_code(rule_code)
    row = await pg.fetchrow("DELETE FROM aml_red_flag_rules WHERE rule_code = $1 RETURNING id", rc)
    return row is not None


async def bulk_upsert_from_json(
    pg: PostgresClient,
    items: List[Dict[str, Any]],
    *,
    updated_by: str,
) -> Dict[str, Any]:
    """Upsert many rules from JSON objects. Returns counts."""
    ok = 0
    errors: List[str] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            errors.append(f"Item {i}: not an object")
            continue
        title = str(raw.get("title") or raw.get("rule") or "").strip()
        rc_raw = raw.get("rule_code") or raw.get("code")
        if not rc_raw and title:
            rc_raw = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:128] or "red_flag"
        try:
            rc = validate_rule_code(str(rc_raw or ""))
        except ValueError as e:
            errors.append(f"Item {i}: {e}")
            continue
        if not title:
            title = rc.replace("_", " ").title()
        desc = str(raw.get("description") or raw.get("red_flag") or "").strip()
        if not desc:
            errors.append(f"Item {i} ({rc}): description required")
            continue
        enabled = raw.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
        patterns = raw.get("match_patterns") or raw.get("patterns") or raw.get("keywords")
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list):
            patterns = []
        await upsert_rule(
            pg,
            rule_code=rc,
            title=title or rc,
            description=desc,
            enabled=bool(enabled),
            match_patterns=[str(x) for x in patterns],
            updated_by=updated_by,
        )
        ok += 1
    return {"upserted": ok, "errors": errors}
