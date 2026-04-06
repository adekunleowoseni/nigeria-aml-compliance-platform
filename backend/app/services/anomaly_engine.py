from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from app.config import settings
from app.core.logging import get_logger
from app.services.llm.client import get_llm_client

log = get_logger(component="anomaly_engine")


@dataclass
class AnomalyAssessment:
    anomaly_score: float  # 0..1 (higher = more anomalous)
    triggered: bool
    reason: str
    llm_summary: Optional[str] = None


def _parse_hour_from_txn(txn: Dict[str, Any]) -> Optional[int]:
    ts = txn.get("timestamp")
    if isinstance(ts, datetime):
        return ts.hour
    ca = txn.get("created_at")
    if isinstance(ca, datetime):
        return ca.hour
    if isinstance(ca, str):
        try:
            # ISO-8601 from JSON / model_dump(mode="json")
            if "T" in ca:
                h = ca.split("T", 1)[1]
                return int(h.split(":", 1)[0])
        except (ValueError, IndexError):
            return None
    return None


def _features(txn: Dict[str, Any]) -> np.ndarray:
    """
    Feature vector for Isolation Forest.
    In production, this should come from a Postgres feature-engineering view.
    """
    amount = float(txn.get("amount") or 0.0)
    currency = (txn.get("currency") or "NGN").upper()
    tx_type = (txn.get("transaction_type") or "transfer").lower()
    hour = _parse_hour_from_txn(txn)
    # Simple encoding
    currency_code = 1.0 if currency == "NGN" else 0.0
    is_wire = 1.0 if "wire" in tx_type else 0.0
    is_cash = 1.0 if "cash" in tx_type else 0.0
    hour_val = float(hour if hour is not None else 12)
    return np.array([amount, currency_code, is_wire, is_cash, hour_val], dtype=np.float64)


class IsolationForestEngine:
    def __init__(self):
        self._model = IsolationForest(
            n_estimators=200,
            contamination=0.02,
            random_state=42,
        )
        self._fitted = False

    def fit_if_needed(self, txns: List[Dict[str, Any]]) -> None:
        if self._fitted:
            return
        if len(txns) < 50:
            # Not enough baseline yet.
            return
        X = np.vstack([_features(t) for t in txns])
        self._model.fit(X)
        self._fitted = True
        log.info("isoforest_fitted", n=len(txns))

    def score(self, txn: Dict[str, Any]) -> float:
        if not self._fitted:
            # fallback heuristic before model is trained
            amt = float(txn.get("amount") or 0.0)
            return float(min(1.0, amt / 50_000_000.0))
        X = _features(txn).reshape(1, -1)
        # decision_function: higher = less abnormal. score_samples: higher = less abnormal.
        raw = float(self._model.score_samples(X)[0])
        # Normalize to 0..1 "anomaly_score" with a squashing function.
        # Raw values are usually around [-0.8, -0.3] depending on data.
        score = 1.0 / (1.0 + np.exp(10.0 * (raw + 0.45)))
        return float(np.clip(score, 0.0, 1.0))


def score_transaction_for_bulk_simulation(
    txn_dict: Dict[str, Any],
    baseline: List[Dict[str, Any]],
    engine_state: Dict[str, Any],
    *,
    refit_every: int = 500,
) -> float:
    """
    Score one transaction using a per-customer Isolation Forest that refits periodically.
    Used for large (e.g. 10-year) simulations without refitting on every row.
    """
    if len(baseline) < 50:
        return IsolationForestEngine().score(txn_dict)

    eng: IsolationForestEngine | None = engine_state.get("engine")
    last_fit: int = int(engine_state.get("last_fit_size", 0))
    need_refit = eng is None or not eng._fitted or (len(baseline) - last_fit) >= refit_every
    if need_refit:
        eng = IsolationForestEngine()
        eng.fit_if_needed(baseline)
        engine_state["engine"] = eng
        engine_state["last_fit_size"] = len(baseline)
    assert eng is not None
    return eng.score(txn_dict)


def compute_anomaly_score_bulk(
    txn_dict: Dict[str, Any],
    baseline: List[Dict[str, Any]],
    engine_state: Dict[str, Any],
    *,
    refit_every: int = 500,
) -> AnomalyAssessment:
    s = score_transaction_for_bulk_simulation(txn_dict, baseline, engine_state, refit_every=refit_every)
    triggered = s >= float(settings.anomaly_threshold)
    reason = "IsolationForest anomaly score above threshold" if triggered else "No anomaly trigger"
    if triggered:
        reason = f"{reason} (bulk simulation; LLM skipped)"
    return AnomalyAssessment(anomaly_score=s, triggered=triggered, reason=reason, llm_summary=None)


async def assess_transaction(
    txn: Dict[str, Any],
    baseline_txns: List[Dict[str, Any]],
    customer_profile: Optional[Dict[str, Any]] = None,
    *,
    skip_llm: bool = False,
) -> AnomalyAssessment:
    engine = IsolationForestEngine()
    engine.fit_if_needed(baseline_txns)
    s = engine.score(txn)
    triggered = s >= float(settings.anomaly_threshold)
    reason = "IsolationForest anomaly score above threshold" if triggered else "No anomaly trigger"

    llm_summary = None
    if triggered and not skip_llm:
        profile_text = f"Customer profile: {customer_profile}" if customer_profile else "Customer profile: (unknown)"
        remarks = txn.get("narrative") or txn.get("remarks") or ""
        prompt = (
            "You are an AML decision-support assistant. Summarize why this may be suspicious using AML typologies "
            "(smurfing/fan-in, layering/cycles, profile mismatch, velocity). Provide a short recommendation.\n\n"
            f"{profile_text}\n"
            f"Transaction: {txn}\n"
            f"Remarks: {remarks}\n"
            f"Anomaly score s(x,n)={s:.2f} (trigger if >={settings.anomaly_threshold:.2f})\n"
        )
        try:
            llm = get_llm_client()
            result = await llm.generate(prompt)
            llm_summary = result.content.strip() or None
        except Exception:
            log.exception("llm_generate_failed")
    elif triggered and skip_llm:
        reason = f"{reason} (LLM skipped in bulk simulation)"

    return AnomalyAssessment(anomaly_score=s, triggered=triggered, reason=reason, llm_summary=llm_summary)

