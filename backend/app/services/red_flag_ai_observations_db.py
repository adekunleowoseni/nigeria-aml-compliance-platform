"""Append-only log of LLM red-flag catalog mapping (analytics / future rule design; not model training)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.db.postgres_client import PostgresClient


async def ensure_red_flag_ai_observations_schema(pg: PostgresClient) -> None:
    await pg.execute(
        """
        CREATE TABLE IF NOT EXISTS aml_red_flag_ai_observations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            transaction_id TEXT,
            customer_id TEXT NOT NULL,
            matched_rule_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
            additional_suspicions JSONB NOT NULL DEFAULT '[]'::jsonb,
            pattern_matched_rule_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
            request_edd BOOLEAN,
            model_provider TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


async def insert_observation(
    pg: PostgresClient,
    *,
    transaction_id: Optional[str],
    customer_id: str,
    matched_rule_codes: List[str],
    additional_suspicions: List[Dict[str, Any]],
    pattern_matched_rule_codes: List[str],
    request_edd: Optional[bool],
    model_provider: Optional[str],
) -> None:
    await pg.execute(
        """
        INSERT INTO aml_red_flag_ai_observations (
            transaction_id, customer_id, matched_rule_codes, additional_suspicions,
            pattern_matched_rule_codes, request_edd, model_provider
        )
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6, $7);
        """,
        transaction_id,
        customer_id[:256],
        json.dumps(matched_rule_codes, default=str),
        json.dumps(additional_suspicions, default=str),
        json.dumps(pattern_matched_rule_codes, default=str),
        request_edd,
        (model_provider or "")[:64] or None,
    )
