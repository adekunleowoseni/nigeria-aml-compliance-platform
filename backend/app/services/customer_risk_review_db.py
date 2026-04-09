from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.db.postgres_client import PostgresClient

_MEMORY_REVIEWS: Dict[str, Dict[str, Any]] = {}
_MEMORY_ALERTS: Dict[str, Dict[str, Any]] = {}
_MEMORY_RULES: Dict[str, Any] = {}

DEFAULT_REVIEW_RULES: Dict[str, Any] = {
    "high_months": 12,
    "medium_months": 18,
    "low_months": 36,
    "student_monthly_turnover_recommend_corporate_ngn": 10_000_000.0,
    "id_expiry_warning_days": 0,
    "require_additional_docs_when_monthly_turnover_above_ngn": 20_000_000.0,
}


def normalize_risk_rating(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in {"high", "medium", "low"}:
        return v
    return "medium"


def add_review_cycle(last_review_date: date, risk_rating: str) -> date:
    rr = normalize_risk_rating(risk_rating)
    if rr == "high":
        return date(last_review_date.year + 1, last_review_date.month, min(last_review_date.day, 28))
    if rr == "medium":
        month = last_review_date.month + 6
        year = last_review_date.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        return date(year, month, min(last_review_date.day, 28))
    return date(last_review_date.year + 3, last_review_date.month, min(last_review_date.day, 28))


def add_review_cycle_with_rules(last_review_date: date, risk_rating: str, rules: Dict[str, Any]) -> date:
    rr = normalize_risk_rating(risk_rating)
    if rr == "high":
        months = int(rules.get("high_months") or 12)
    elif rr == "low":
        months = int(rules.get("low_months") or 36)
    else:
        months = int(rules.get("medium_months") or 18)
    months = max(1, months)
    month = last_review_date.month + months
    year = last_review_date.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    return date(year, month, min(last_review_date.day, 28))


def _json_dump(v: Any) -> str:
    try:
        return json.dumps(v or {}, ensure_ascii=True)
    except Exception:
        return "{}"


def _json_load(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        try:
            x = json.loads(v)
            return x if isinstance(x, dict) else {}
        except Exception:
            return {}
    return {}


async def ensure_customer_risk_review_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS aml_customer_risk_review (
            review_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            reviewed_at DATE NOT NULL,
            risk_rating TEXT NOT NULL,
            previous_risk_rating TEXT,
            next_review_due_at DATE NOT NULL,
            id_card_expiry_at DATE,
            bvn_linked_accounts_count INTEGER NOT NULL DEFAULT 0,
            profile_changed BOOLEAN NOT NULL DEFAULT FALSE,
            account_update_within_period BOOLEAN NOT NULL DEFAULT FALSE,
            management_approval_within_period BOOLEAN NOT NULL DEFAULT FALSE,
            age_commensurate BOOLEAN NOT NULL DEFAULT TRUE,
            activity_commensurate BOOLEAN NOT NULL DEFAULT TRUE,
            pep_flag BOOLEAN NOT NULL DEFAULT FALSE,
            expected_turnover_match BOOLEAN NOT NULL DEFAULT TRUE,
            expected_activity_match BOOLEAN NOT NULL DEFAULT TRUE,
            expected_lodgement_match BOOLEAN NOT NULL DEFAULT TRUE,
            suggested_risk_profile TEXT NOT NULL DEFAULT 'medium',
            recommendation TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'reviewed',
            checklist_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_aml_customer_risk_review_customer ON aml_customer_risk_review(customer_id);
        CREATE INDEX IF NOT EXISTS idx_aml_customer_risk_review_due ON aml_customer_risk_review(next_review_due_at);
        """
    )
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS aml_customer_risk_review_alert (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            review_id TEXT,
            due_date DATE NOT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            recipient_email TEXT NOT NULL,
            recipient_role TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'individual',
            status TEXT NOT NULL DEFAULT 'sent',
            detail TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_aml_customer_risk_review_alert_customer ON aml_customer_risk_review_alert(customer_id);
        CREATE INDEX IF NOT EXISTS idx_aml_customer_risk_review_alert_due ON aml_customer_risk_review_alert(due_date);
        """
    )
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS aml_customer_risk_review_rules (
            id INTEGER PRIMARY KEY,
            high_months INTEGER NOT NULL DEFAULT 12,
            medium_months INTEGER NOT NULL DEFAULT 18,
            low_months INTEGER NOT NULL DEFAULT 36,
            student_monthly_turnover_recommend_corporate_ngn DOUBLE PRECISION NOT NULL DEFAULT 10000000,
            id_expiry_warning_days INTEGER NOT NULL DEFAULT 0,
            require_additional_docs_when_monthly_turnover_above_ngn DOUBLE PRECISION NOT NULL DEFAULT 20000000,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        INSERT INTO aml_customer_risk_review_rules (id)
        VALUES (1)
        ON CONFLICT (id) DO NOTHING;
        """
    )


async def upsert_customer_risk_review(pg: Optional[PostgresClient], row: Dict[str, Any]) -> Dict[str, Any]:
    review_id = str(row.get("review_id") or uuid4().hex)
    payload = dict(row)
    payload["review_id"] = review_id
    payload["risk_rating"] = normalize_risk_rating(str(payload.get("risk_rating") or "medium"))
    payload["suggested_risk_profile"] = normalize_risk_rating(str(payload.get("suggested_risk_profile") or "medium"))
    payload["checklist_json"] = _json_load(payload.get("checklist_json"))
    if pg is not None:
        await pg.execute(
            """
            INSERT INTO aml_customer_risk_review (
                review_id, customer_id, reviewed_at, risk_rating, previous_risk_rating, next_review_due_at,
                id_card_expiry_at, bvn_linked_accounts_count, profile_changed, account_update_within_period,
                management_approval_within_period, age_commensurate, activity_commensurate, pep_flag,
                expected_turnover_match, expected_activity_match, expected_lodgement_match,
                suggested_risk_profile, recommendation, status, checklist_json, updated_at
            )
            VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,NOW()
            )
            ON CONFLICT (review_id) DO UPDATE SET
                customer_id = EXCLUDED.customer_id,
                reviewed_at = EXCLUDED.reviewed_at,
                risk_rating = EXCLUDED.risk_rating,
                previous_risk_rating = EXCLUDED.previous_risk_rating,
                next_review_due_at = EXCLUDED.next_review_due_at,
                id_card_expiry_at = EXCLUDED.id_card_expiry_at,
                bvn_linked_accounts_count = EXCLUDED.bvn_linked_accounts_count,
                profile_changed = EXCLUDED.profile_changed,
                account_update_within_period = EXCLUDED.account_update_within_period,
                management_approval_within_period = EXCLUDED.management_approval_within_period,
                age_commensurate = EXCLUDED.age_commensurate,
                activity_commensurate = EXCLUDED.activity_commensurate,
                pep_flag = EXCLUDED.pep_flag,
                expected_turnover_match = EXCLUDED.expected_turnover_match,
                expected_activity_match = EXCLUDED.expected_activity_match,
                expected_lodgement_match = EXCLUDED.expected_lodgement_match,
                suggested_risk_profile = EXCLUDED.suggested_risk_profile,
                recommendation = EXCLUDED.recommendation,
                status = EXCLUDED.status,
                checklist_json = EXCLUDED.checklist_json,
                updated_at = NOW()
            """,
            review_id,
            payload["customer_id"],
            payload["reviewed_at"],
            payload["risk_rating"],
            payload.get("previous_risk_rating"),
            payload["next_review_due_at"],
            payload.get("id_card_expiry_at"),
            int(payload.get("bvn_linked_accounts_count") or 0),
            bool(payload.get("profile_changed")),
            bool(payload.get("account_update_within_period")),
            bool(payload.get("management_approval_within_period")),
            bool(payload.get("age_commensurate", True)),
            bool(payload.get("activity_commensurate", True)),
            bool(payload.get("pep_flag")),
            bool(payload.get("expected_turnover_match", True)),
            bool(payload.get("expected_activity_match", True)),
            bool(payload.get("expected_lodgement_match", True)),
            payload["suggested_risk_profile"],
            str(payload.get("recommendation") or ""),
            str(payload.get("status") or "reviewed"),
            _json_dump(payload["checklist_json"]),
        )
    payload["review_id"] = review_id
    _MEMORY_REVIEWS[review_id] = payload
    return payload


async def latest_review_for_customer(pg: Optional[PostgresClient], customer_id: str) -> Optional[Dict[str, Any]]:
    cid = (customer_id or "").strip()
    if not cid:
        return None
    if pg is not None:
        row = await pg.fetchrow(
            """
            SELECT * FROM aml_customer_risk_review
            WHERE customer_id = $1
            ORDER BY reviewed_at DESC, created_at DESC
            LIMIT 1
            """,
            cid,
        )
        if row:
            row["checklist_json"] = _json_load(row.get("checklist_json"))
            return row
    rows = [x for x in _MEMORY_REVIEWS.values() if str(x.get("customer_id")) == cid]
    rows.sort(key=lambda r: str(r.get("reviewed_at") or ""), reverse=True)
    return rows[0] if rows else None


async def list_due_reviews(
    pg: Optional[PostgresClient], *, as_of: date, days_ahead: int = 0, limit: int = 500
) -> List[Dict[str, Any]]:
    end_date = as_of + timedelta(days=max(0, days_ahead))
    if pg is not None:
        rows = await pg.fetch(
            """
            SELECT rr.review_id, rr.customer_id, rr.risk_rating, rr.next_review_due_at, rr.reviewed_at,
                   k.customer_name, k.account_number, k.id_number
            FROM aml_customer_risk_review rr
            LEFT JOIN aml_customer_kyc k ON k.customer_id = rr.customer_id
            WHERE rr.next_review_due_at <= $1
            ORDER BY rr.next_review_due_at ASC
            LIMIT $2
            """,
            end_date,
            limit,
        )
        return rows
    out: List[Dict[str, Any]] = []
    for r in _MEMORY_REVIEWS.values():
        nd = r.get("next_review_due_at")
        if isinstance(nd, date) and nd <= end_date:
            out.append(dict(r))
    out.sort(key=lambda r: str(r.get("next_review_due_at") or ""))
    return out[:limit]


async def list_reviews_for_customer(pg: Optional[PostgresClient], customer_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    cid = (customer_id or "").strip()
    if not cid:
        return []
    if pg is not None:
        rows = await pg.fetch(
            "SELECT * FROM aml_customer_risk_review WHERE customer_id = $1 ORDER BY reviewed_at DESC, created_at DESC LIMIT $2",
            cid,
            limit,
        )
        for r in rows:
            r["checklist_json"] = _json_load(r.get("checklist_json"))
        return rows
    rows = [dict(x) for x in _MEMORY_REVIEWS.values() if str(x.get("customer_id")) == cid]
    rows.sort(key=lambda r: str(r.get("reviewed_at") or ""), reverse=True)
    return rows[:limit]


async def get_customer_review_rules(pg: Optional[PostgresClient]) -> Dict[str, Any]:
    if pg is not None:
        row = await pg.fetchrow("SELECT * FROM aml_customer_risk_review_rules WHERE id = 1")
        if row:
            return {
                "high_months": int(row.get("high_months") or 12),
                "medium_months": int(row.get("medium_months") or 18),
                "low_months": int(row.get("low_months") or 36),
                "student_monthly_turnover_recommend_corporate_ngn": float(
                    row.get("student_monthly_turnover_recommend_corporate_ngn") or 10_000_000.0
                ),
                "id_expiry_warning_days": int(row.get("id_expiry_warning_days") or 0),
                "require_additional_docs_when_monthly_turnover_above_ngn": float(
                    row.get("require_additional_docs_when_monthly_turnover_above_ngn") or 20_000_000.0
                ),
            }
    return dict(DEFAULT_REVIEW_RULES, **_MEMORY_RULES)


async def upsert_customer_review_rules(pg: Optional[PostgresClient], rules: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_REVIEW_RULES)
    for key in DEFAULT_REVIEW_RULES.keys():
        if key in rules:
            merged[key] = rules[key]
    merged["high_months"] = max(1, int(merged["high_months"]))
    merged["medium_months"] = max(1, int(merged["medium_months"]))
    merged["low_months"] = max(1, int(merged["low_months"]))
    merged["id_expiry_warning_days"] = max(0, int(merged["id_expiry_warning_days"]))
    merged["student_monthly_turnover_recommend_corporate_ngn"] = float(
        merged["student_monthly_turnover_recommend_corporate_ngn"]
    )
    merged["require_additional_docs_when_monthly_turnover_above_ngn"] = float(
        merged["require_additional_docs_when_monthly_turnover_above_ngn"]
    )
    if pg is not None:
        await pg.execute(
            """
            INSERT INTO aml_customer_risk_review_rules (
                id, high_months, medium_months, low_months,
                student_monthly_turnover_recommend_corporate_ngn, id_expiry_warning_days,
                require_additional_docs_when_monthly_turnover_above_ngn, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
            ON CONFLICT (id) DO UPDATE SET
                high_months = EXCLUDED.high_months,
                medium_months = EXCLUDED.medium_months,
                low_months = EXCLUDED.low_months,
                student_monthly_turnover_recommend_corporate_ngn = EXCLUDED.student_monthly_turnover_recommend_corporate_ngn,
                id_expiry_warning_days = EXCLUDED.id_expiry_warning_days,
                require_additional_docs_when_monthly_turnover_above_ngn = EXCLUDED.require_additional_docs_when_monthly_turnover_above_ngn,
                updated_at = NOW()
            """,
            1,
            merged["high_months"],
            merged["medium_months"],
            merged["low_months"],
            merged["student_monthly_turnover_recommend_corporate_ngn"],
            merged["id_expiry_warning_days"],
            merged["require_additional_docs_when_monthly_turnover_above_ngn"],
        )
    _MEMORY_RULES.update(merged)
    return merged


async def insert_review_alert_log(pg: Optional[PostgresClient], row: Dict[str, Any]) -> Dict[str, Any]:
    rid = str(row.get("id") or uuid4().hex)
    payload = dict(row)
    payload["id"] = rid
    payload["sent_at"] = payload.get("sent_at") or datetime.utcnow().isoformat()
    if pg is not None:
        await pg.execute(
            """
            INSERT INTO aml_customer_risk_review_alert
                (id, customer_id, review_id, due_date, sent_at, recipient_email, recipient_role, mode, status, detail)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            rid,
            payload["customer_id"],
            payload.get("review_id"),
            payload["due_date"],
            payload["sent_at"],
            payload["recipient_email"],
            payload["recipient_role"],
            payload.get("mode", "individual"),
            payload.get("status", "sent"),
            payload.get("detail"),
        )
    _MEMORY_ALERTS[rid] = payload
    return payload
