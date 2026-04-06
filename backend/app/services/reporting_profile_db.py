"""Institution reporting profile + regulatory return calendar (CBN-aligned, bank presets)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.db.postgres_client import PostgresClient

# slug, title, family, frequency, cron, day_of_month, day_of_week, submission_offset_days, reminder_days_before
_DEFAULT_CALENDAR_ROWS: List[tuple] = [
    (
        "ftr_threshold_review",
        "FTR — daily review of threshold-eligible cross-border / wire activity (CBN)",
        "ftr",
        "daily",
        None,
        None,
        None,
        0,
        1,
    ),
    (
        "ctr_monthly_pack",
        "CTR — monthly aggregation and goAML-style XML preparation",
        "ctr",
        "monthly",
        None,
        5,
        None,
        2,
        3,
    ),
    (
        "str_cco_weekly",
        "STR pipeline — weekly CCO submission readiness review",
        "str",
        "weekly",
        None,
        None,
        0,
        0,
        2,
    ),
    (
        "goaml_bundle_monthly",
        "Regulatory bundle — monthly board / management pack alignment",
        "goaml_bundle",
        "monthly",
        None,
        1,
        None,
        0,
        7,
    ),
]

DEFAULT_OUTPUTS: Dict[str, Any] = {
    "str": ["word", "xml_goaml"],
    "sar": ["word", "xml_goaml"],
    "ctr": ["xml_goaml"],
    "aop": ["pdf"],
    "soa": ["word"],
    "ftr": ["xml", "csv"],
    "estr": ["word", "xml_goaml"],
    "nfiu_cir": ["xml_goaml", "word"],
}

VALID_PACKS = frozenset({"cbn_default", "gtbank", "zenith", "uba", "access", "custom"})
VALID_NARRATIVE = frozenset({"cbn_formal", "bank_standard", "concise"})
VALID_FREQUENCIES = frozenset({"daily", "weekly", "monthly", "quarterly", "annual", "cron"})


async def ensure_reporting_profile_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS institution_reporting_profile (
            id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            template_pack VARCHAR(32) NOT NULL DEFAULT 'cbn_default',
            institution_display_name TEXT NOT NULL DEFAULT 'Reporting Institution',
            reporting_entity_name TEXT NOT NULL DEFAULT 'Licensed Financial Institution (CBN returns)',
            entity_registration_ref TEXT NOT NULL DEFAULT 'RC-________',
            default_outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
            narrative_style VARCHAR(32) NOT NULL DEFAULT 'cbn_formal',
            updated_by TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT institution_reporting_profile_pack_chk CHECK (
              template_pack IN ('cbn_default', 'gtbank', 'zenith', 'uba', 'access', 'custom')
            ),
            CONSTRAINT institution_reporting_profile_narr_chk CHECK (
              narrative_style IN ('cbn_formal', 'bank_standard', 'concise')
            )
        );
        """
    )
    await pg.execute(
        """
        INSERT INTO institution_reporting_profile (id) VALUES (1)
        ON CONFLICT (id) DO NOTHING;
        """
    )
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS regulatory_report_calendar (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug VARCHAR(128) NOT NULL UNIQUE,
            title TEXT NOT NULL,
            report_family VARCHAR(64) NOT NULL,
            frequency VARCHAR(32) NOT NULL,
            cron_expression VARCHAR(128),
            day_of_month SMALLINT,
            day_of_week SMALLINT,
            submission_offset_days INT NOT NULL DEFAULT 0,
            reminder_days_before INT NOT NULL DEFAULT 1,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            preferred_formats JSONB NOT NULL DEFAULT '{}'::jsonb,
            notes TEXT,
            updated_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT regulatory_report_calendar_freq_chk CHECK (
              frequency IN ('daily', 'weekly', 'monthly', 'quarterly', 'annual', 'cron')
            )
        );
        """
    )
    await pg.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_regulatory_calendar_family ON regulatory_report_calendar (report_family);
        """
    )
    ncal = await pg.fetchval("SELECT COUNT(*)::int FROM regulatory_report_calendar")
    if int(ncal or 0) == 0:
        for slug, title, fam, freq, cron, dom, dow, off, rem in _DEFAULT_CALENDAR_ROWS:
            await pg.execute(
                """
                INSERT INTO regulatory_report_calendar (
                  slug, title, report_family, frequency, cron_expression, day_of_month, day_of_week,
                  submission_offset_days, reminder_days_before, enabled, preferred_formats, notes
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, TRUE, '{}'::jsonb, $10)
                ON CONFLICT (slug) DO NOTHING
                """,
                slug,
                title,
                fam,
                freq,
                cron,
                dom,
                dow,
                off,
                rem,
                "CBN-aligned starter entry — edit or disable in Admin → Reporting configuration.",
            )


def _row_profile(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, UUID):
            out[k] = str(v)
    if isinstance(out.get("default_outputs"), str):
        try:
            out["default_outputs"] = json.loads(out["default_outputs"])
        except Exception:
            out["default_outputs"] = {}
    return out


def _row_cal(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, UUID):
            out[k] = str(v)
    if isinstance(out.get("preferred_formats"), str):
        try:
            out["preferred_formats"] = json.loads(out["preferred_formats"])
        except Exception:
            out["preferred_formats"] = {}
    return out


async def get_reporting_profile_row(pg: PostgresClient) -> Dict[str, Any]:
    row = await pg.fetchrow("SELECT * FROM institution_reporting_profile WHERE id = 1")
    if not row:
        return {}
    return _row_profile(dict(row))


async def upsert_reporting_profile(
    pg: PostgresClient,
    *,
    template_pack: str,
    institution_display_name: str,
    reporting_entity_name: str,
    entity_registration_ref: str,
    default_outputs: Dict[str, Any],
    narrative_style: str,
    updated_by: Optional[str],
) -> Dict[str, Any]:
    tp = template_pack.strip().lower()
    if tp not in VALID_PACKS:
        raise ValueError("invalid template_pack")
    ns = narrative_style.strip().lower()
    if ns not in VALID_NARRATIVE:
        raise ValueError("invalid narrative_style")
    r = await pg.fetchrow(
        """
        INSERT INTO institution_reporting_profile (
          id, template_pack, institution_display_name, reporting_entity_name,
          entity_registration_ref, default_outputs, narrative_style, updated_by, updated_at
        ) VALUES (
          1, $1, $2, $3, $4, $5::jsonb, $6, $7, NOW()
        )
        ON CONFLICT (id) DO UPDATE SET
          template_pack = EXCLUDED.template_pack,
          institution_display_name = EXCLUDED.institution_display_name,
          reporting_entity_name = EXCLUDED.reporting_entity_name,
          entity_registration_ref = EXCLUDED.entity_registration_ref,
          default_outputs = EXCLUDED.default_outputs,
          narrative_style = EXCLUDED.narrative_style,
          updated_by = EXCLUDED.updated_by,
          updated_at = NOW()
        RETURNING *
        """,
        tp,
        institution_display_name.strip(),
        reporting_entity_name.strip(),
        entity_registration_ref.strip(),
        default_outputs,
        ns,
        updated_by,
    )
    return _row_profile(dict(r)) if r else {}


async def list_calendar_entries(pg: PostgresClient) -> List[Dict[str, Any]]:
    rows = await pg.fetch("SELECT * FROM regulatory_report_calendar ORDER BY report_family, title")
    return [_row_cal(dict(r)) for r in rows]


async def insert_calendar_entry(
    pg: PostgresClient,
    *,
    slug: str,
    title: str,
    report_family: str,
    frequency: str,
    cron_expression: Optional[str],
    day_of_month: Optional[int],
    day_of_week: Optional[int],
    submission_offset_days: int,
    reminder_days_before: int,
    enabled: bool,
    preferred_formats: Dict[str, Any],
    notes: Optional[str],
    updated_by: Optional[str],
) -> Dict[str, Any]:
    fq = frequency.strip().lower()
    if fq not in VALID_FREQUENCIES:
        raise ValueError("invalid frequency")
    r = await pg.fetchrow(
        """
        INSERT INTO regulatory_report_calendar (
          slug, title, report_family, frequency, cron_expression, day_of_month, day_of_week,
          submission_offset_days, reminder_days_before, enabled, preferred_formats, notes, updated_by, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, NOW())
        RETURNING *
        """,
        slug.strip().lower()[:128],
        title.strip(),
        report_family.strip().lower()[:64],
        fq,
        (cron_expression or "").strip() or None,
        day_of_month,
        day_of_week,
        int(submission_offset_days),
        int(reminder_days_before),
        bool(enabled),
        preferred_formats,
        (notes or "").strip() or None,
        updated_by,
    )
    return _row_cal(dict(r)) if r else {}


async def update_calendar_entry(
    pg: PostgresClient,
    entry_id: str,
    fields: Dict[str, Any],
    updated_by: Optional[str],
) -> Optional[Dict[str, Any]]:
    sets: List[str] = []
    args: List[Any] = []
    i = 1
    mapping = {
        "title": "title",
        "report_family": "report_family",
        "frequency": "frequency",
        "cron_expression": "cron_expression",
        "day_of_month": "day_of_month",
        "day_of_week": "day_of_week",
        "submission_offset_days": "submission_offset_days",
        "reminder_days_before": "reminder_days_before",
        "enabled": "enabled",
        "notes": "notes",
    }
    for key, col in mapping.items():
        if key not in fields:
            continue
        sets.append(f"{col} = ${i}")
        args.append(fields[key])
        i += 1
    if "preferred_formats" in fields:
        sets.append(f"preferred_formats = ${i}::jsonb")
        args.append(fields["preferred_formats"])
        i += 1
    if not sets:
        row = await pg.fetchrow("SELECT * FROM regulatory_report_calendar WHERE id = $1::uuid", entry_id)
        return _row_cal(dict(row)) if row else None
    sets.append(f"updated_by = ${i}")
    args.append(updated_by)
    i += 1
    sets.append("updated_at = NOW()")
    args.append(entry_id)
    q = f"UPDATE regulatory_report_calendar SET {', '.join(sets)} WHERE id = ${i}::uuid RETURNING *"
    row = await pg.fetchrow(q, *args)
    return _row_cal(dict(row)) if row else None


async def delete_calendar_entry(pg: PostgresClient, entry_id: str) -> bool:
    r = await pg.execute("DELETE FROM regulatory_report_calendar WHERE id = $1::uuid", entry_id)
    return str(r).endswith("DELETE 1")


async def get_calendar_entry(pg: PostgresClient, entry_id: str) -> Optional[Dict[str, Any]]:
    row = await pg.fetchrow("SELECT * FROM regulatory_report_calendar WHERE id = $1::uuid", entry_id)
    return _row_cal(dict(row)) if row else None
