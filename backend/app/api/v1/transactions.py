from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.api.v1.alerts import _ALERTS
from app.core.security import get_current_user
from app.models.alert import AlertResponse
from app.models.transaction import GraphResponse, TransactionCreate, TransactionResponse
from app.services.anomaly_engine import assess_transaction, compute_anomaly_score_bulk
from app.services.temporal_simulation import generate_temporal_dataset
from app.services.typology_rules import evaluate_typologies

router = APIRouter(prefix="/transactions")

# In-memory store for a bootstrappable API.
# Replace with Postgres/Neo4j in later iterations.
_TXNS: Dict[str, TransactionResponse] = {}
_JOBS: Dict[str, Dict[str, Any]] = {}


def _prior_customer_baseline(txn: TransactionResponse) -> List[Dict[str, Any]]:
    """Transactions for the same customer strictly before this event (10y pattern learning)."""
    prior: List[TransactionResponse] = [
        t
        for t in _TXNS.values()
        if t.customer_id == txn.customer_id and t.created_at < txn.created_at and t.id != txn.id
    ]
    return [t.model_dump() for t in prior]


async def _process_transaction_async(txn_id: str, *, skip_llm: bool = False) -> None:
    txn = _TXNS.get(txn_id)
    if not txn:
        return
    # Cognitive pipeline: IsolationForest on this customer's own history (plus optional global context).
    baseline = _prior_customer_baseline(txn)
    assessment = await assess_transaction(
        txn.model_dump(),
        baseline_txns=baseline,
        customer_profile={"role": "unknown", "customer_id": txn.customer_id},
        skip_llm=skip_llm,
    )
    md0 = txn.metadata or {}
    profile_label = (
        str(md0.get("profile") or md0.get("pattern") or "") if isinstance(md0, dict) else ""
    )
    typ_hits = evaluate_typologies(txn.model_dump(), baseline, customer_profile_label=profile_label)
    typ_rule_ids = [h.rule_id for h in typ_hits]

    txn.risk_score = float(assessment.anomaly_score)
    triggered = assessment.triggered or bool(typ_hits)
    if triggered:
        md = dict(txn.metadata or {})
        if assessment.llm_summary:
            md["decision_support_summary"] = assessment.llm_summary
        md["trigger_reason"] = assessment.reason
        if typ_hits:
            md["typology_hits"] = [h.rule_id for h in typ_hits]
            md["typology_titles"] = [h.title for h in typ_hits[:8]]
        txn.metadata = md
        scenario = md.get("simulation_scenario")
        rule_ids: List[str] = []
        if assessment.triggered:
            rule_ids.append("RULE-ANOMALY")
        rule_ids.extend(typ_rule_ids)
        if scenario:
            rule_ids.append(f"SIM-{scenario}")
        seen: set[str] = set()
        rule_ids = [x for x in rule_ids if not (x in seen or seen.add(x))]

        summary_parts: List[str] = []
        if typ_hits:
            summary_parts.append(f"{typ_hits[0].title}: {typ_hits[0].narrative[:220]}")
        if assessment.llm_summary:
            summary_parts.append(assessment.llm_summary[:220])
        if not summary_parts:
            summary_parts.append((f"[{scenario}] " if scenario else "") + (txn.narrative or "AML review required"))
        summary = " | ".join(summary_parts)
        severity = max(
            float(assessment.anomaly_score),
            min(0.95, 0.35 + 0.07 * len(typ_hits)),
        )
        alert = AlertResponse(
            transaction_id=txn.id,
            customer_id=txn.customer_id,
            severity=severity,
            status="open",
            rule_ids=rule_ids,
            summary=summary[:500],
        )
        _ALERTS[alert.id] = alert
        txn.alert_id = alert.id
    txn.status = "processed"
    txn.updated_at = datetime.utcnow()
    _TXNS[txn_id] = txn


@router.post("/ingest", response_model=TransactionResponse)
async def ingest_transaction(
    body: TransactionCreate,
    background: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
) -> TransactionResponse:
    txn = TransactionResponse(
        customer_id=body.customer_id,
        amount=body.amount,
        currency=body.currency,
        transaction_type=body.transaction_type,
        narrative=body.narrative,
        counterparty_id=body.counterparty_id,
        counterparty_name=body.counterparty_name,
        metadata=body.metadata,
        status="received",
        created_at=datetime.utcnow(),
    )
    _TXNS[txn.id] = txn
    background.add_task(_process_transaction_async, txn.id)
    return txn


@router.post("/bulk-ingest")
async def bulk_ingest(
    body: List[TransactionCreate],
    background: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
):
    job_id = str(uuid4())
    _JOBS[job_id] = {"status": "queued", "total": len(body), "processed": 0}

    async def _run_job():
        _JOBS[job_id]["status"] = "running"
        for item in body:
            txn = TransactionResponse(
                customer_id=item.customer_id,
                amount=item.amount,
                currency=item.currency,
                transaction_type=item.transaction_type,
                narrative=item.narrative,
                counterparty_id=item.counterparty_id,
                counterparty_name=item.counterparty_name,
                metadata=item.metadata,
                status="received",
                created_at=datetime.utcnow(),
            )
            _TXNS[txn.id] = txn
            await _process_transaction_async(txn.id)
            _JOBS[job_id]["processed"] += 1
        _JOBS[job_id]["status"] = "done"

    background.add_task(_run_job)
    return {"job_id": job_id, "status": "queued"}


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> TransactionResponse:
    txn = _TXNS.get(transaction_id)
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return txn


@router.get("/", response_model=Dict[str, Any])
async def list_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    entity_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    items = list(_TXNS.values())
    if status_filter:
        items = [t for t in items if t.status == status_filter]
    if min_amount is not None:
        items = [t for t in items if t.amount >= min_amount]
    if max_amount is not None:
        items = [t for t in items if t.amount <= max_amount]

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    return {"items": page_items, "total": total, "skip": start, "limit": page_size}


@router.get("/{transaction_id}/graph", response_model=GraphResponse)
async def get_transaction_graph(
    transaction_id: str,
    depth: int = Query(2, ge=1, le=3),
    user: Dict[str, Any] = Depends(get_current_user),
) -> GraphResponse:
    txn = _TXNS.get(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    # Minimal graph response for UI: one node.
    return GraphResponse(nodes=[{"id": txn.id, "type": "transaction", "properties": txn.model_dump()}], edges=[])


@router.post("/{transaction_id}/analyze")
async def analyze_transaction(
    transaction_id: str,
    background: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if transaction_id not in _TXNS:
        raise HTTPException(status_code=404, detail="Transaction not found")
    background.add_task(_process_transaction_async, transaction_id)
    return {"transaction_id": transaction_id, "status": "queued"}


async def run_temporal_simulation(
    *,
    years: int = 10,
    seed: int = 42,
    clear_existing: bool = True,
    max_transactions: int = 100_000,
    refit_every: int = 500,
) -> Dict[str, Any]:
    """
    Generate ~10 years of synthetic activity per customer, inject AML scenarios,
    score chronologically vs each customer's own history (Isolation Forest with periodic refit).
    """
    if clear_existing:
        _TXNS.clear()
        _ALERTS.clear()
        from app.api.v1.reports import _REPORTS

        _REPORTS.clear()
        from app.services.customer_kyc_db import clear_memory_kyc

        clear_memory_kyc()

    txns, summary = generate_temporal_dataset(years=years, seed=seed, max_transactions=max_transactions)

    for t in txns:
        _TXNS[t.id] = t

    history_by_customer: Dict[str, List[Dict[str, Any]]] = {}
    engine_state_by_customer: Dict[str, Dict[str, Any]] = {}
    alerts_created = 0

    for txn in txns:
        cid = txn.customer_id
        hist = history_by_customer.setdefault(cid, [])
        baseline = list(hist)
        st = engine_state_by_customer.setdefault(cid, {})

        txn_dict = txn.model_dump()
        assessment = compute_anomaly_score_bulk(
            txn_dict,
            baseline,
            st,
            refit_every=refit_every,
        )
        profile_label = ""
        if isinstance(txn_dict.get("metadata"), dict):
            profile_label = str(
                txn_dict["metadata"].get("profile") or txn_dict["metadata"].get("pattern") or ""
            )
        typ_hits = evaluate_typologies(txn_dict, baseline, customer_profile_label=profile_label)
        typ_rule_ids = [h.rule_id for h in typ_hits]
        triggered = assessment.triggered or bool(typ_hits)

        txn.risk_score = float(assessment.anomaly_score)
        if triggered:
            md = dict(txn.metadata or {})
            md["trigger_reason"] = assessment.reason
            if typ_hits:
                md["typology_hits"] = typ_rule_ids
            txn.metadata = md
            scenario = md.get("simulation_scenario")
            rule_ids: List[str] = []
            if assessment.triggered:
                rule_ids.append("RULE-ANOMALY")
            rule_ids.extend(typ_rule_ids)
            if scenario:
                rule_ids.append(f"SIM-{scenario}")
            seen2: set[str] = set()
            rule_ids = [x for x in rule_ids if not (x in seen2 or seen2.add(x))]
            if typ_hits:
                summary_text = f"{typ_hits[0].title}: {typ_hits[0].narrative[:200]}"
            else:
                summary_text = (f"[{scenario}] " if scenario else "") + (
                    txn.narrative or "Anomaly detected vs customer baseline"
                )
            severity = max(
                float(assessment.anomaly_score),
                min(0.95, 0.35 + 0.07 * len(typ_hits)),
            )
            alert = AlertResponse(
                transaction_id=txn.id,
                customer_id=txn.customer_id,
                severity=severity,
                status="open",
                rule_ids=rule_ids,
                summary=summary_text[:500],
            )
            _ALERTS[alert.id] = alert
            txn.alert_id = alert.id
            alerts_created += 1

        txn.status = "processed"
        txn.updated_at = datetime.utcnow()
        _TXNS[txn.id] = txn
        hist.append(txn_dict)

    return {**summary, "alerts_created": alerts_created, "stored_transactions": len(_TXNS)}

