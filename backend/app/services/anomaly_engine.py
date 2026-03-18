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


def _features(txn: Dict[str, Any]) -> np.ndarray:
    """
    Feature vector for Isolation Forest.
    In production, this should come from a Postgres feature-engineering view.
    """
    amount = float(txn.get("amount") or 0.0)
    currency = (txn.get("currency") or "NGN").upper()
    tx_type = (txn.get("transaction_type") or "transfer").lower()
    hour = None
    ts = txn.get("timestamp")
    if isinstance(ts, datetime):
        hour = ts.hour
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


async def assess_transaction(
    txn: Dict[str, Any],
    baseline_txns: List[Dict[str, Any]],
    customer_profile: Optional[Dict[str, Any]] = None,
) -> AnomalyAssessment:
    engine = IsolationForestEngine()
    engine.fit_if_needed(baseline_txns)
    s = engine.score(txn)
    triggered = s >= float(settings.anomaly_threshold)
    reason = "IsolationForest anomaly score above threshold" if triggered else "No anomaly trigger"

    llm_summary = None
    if triggered:
        llm = get_llm_client()
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
            result = await llm.generate(prompt)
            llm_summary = result.content.strip() or None
        except Exception:
            log.exception("llm_generate_failed")

    return AnomalyAssessment(anomaly_score=s, triggered=triggered, reason=reason, llm_summary=llm_summary)

