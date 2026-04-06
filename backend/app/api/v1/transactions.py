from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from app.api.v1.in_memory_stores import _ALERTS, _TXNS
from app.core.security import get_current_user
from app.db.postgres_client import PostgresClient
from app.models.alert import AlertResponse
from app.models.transaction import GraphResponse, TransactionCreate, TransactionResponse
from app.services.anomaly_engine import assess_transaction, compute_anomaly_score_bulk
from app.services.customer_kyc_db import get_or_create_customer_kyc
from app.services.realtime_ai_txn_screening import run_realtime_ai_transaction_screening
from app.services.temporal_simulation import generate_temporal_dataset
from app.services.transaction_analytics import _is_inflow, ytd_calendar_year_inflow_ngn
from app.services.red_flag_ai_matcher import run_red_flag_llm_matcher
from app.services.red_flag_rules_service import evaluate_custom_red_flags
from app.services.typology_rules import TypologyHit, dedupe_typology_hits, evaluate_typologies
from app.services.zone_branch import ensure_txn_aml_geo_metadata, txn_matches_user_scope

router = APIRouter(prefix="/transactions")

_JOBS: Dict[str, Dict[str, Any]] = {}


def _txn_not_soft_deleted(t: TransactionResponse) -> bool:
    return getattr(t, "deleted_at", None) is None


def _persist_txn_geo(txn: TransactionResponse) -> None:
    md = ensure_txn_aml_geo_metadata(txn.metadata if isinstance(txn.metadata, dict) else None, txn.customer_id)
    txn.metadata = md
    _TXNS[txn.id] = txn


def _prior_customer_baseline(txn: TransactionResponse) -> List[Dict[str, Any]]:
    """Transactions for the same customer strictly before this event (10y pattern learning)."""
    prior: List[TransactionResponse] = [
        t
        for t in _TXNS.values()
        if t.customer_id == txn.customer_id and t.created_at < txn.created_at and t.id != txn.id
    ]
    return [t.model_dump() for t in prior]


async def _process_transaction_async(
    txn_id: str,
    pg: Optional[PostgresClient] = None,
    *,
    skip_llm: bool = False,
) -> None:
    txn = _TXNS.get(txn_id)
    if not txn:
        return
    _persist_txn_geo(txn)
    txn = _TXNS.get(txn_id)
    if not txn:
        return
    md0 = txn.metadata if isinstance(txn.metadata, dict) else {}
    skip_llm_effective = skip_llm or (md0.get("demo_skip_llm") is True)
    baseline = _prior_customer_baseline(txn)
    txn_dict = txn.model_dump()
    kyc_segment: Optional[str] = None
    expected_annual_turnover: Optional[float] = None
    customer_remarks: Optional[str] = None
    line_of_business: Optional[str] = None
    customer_name: str = ""
    if pg is not None:
        try:
            kyc = await get_or_create_customer_kyc(pg, txn.customer_id, txn_dict)
            kyc_segment = (kyc.customer_segment or "").strip() or None
            expected_annual_turnover = kyc.expected_annual_turnover
            customer_remarks = (kyc.customer_remarks or "").strip() or None
            line_of_business = (kyc.line_of_business or "").strip() or None
            customer_name = (kyc.customer_name or "").strip()
        except Exception:
            pass
    if not kyc_segment and isinstance(md0, dict):
        raw_seg = md0.get("customer_segment")
        kyc_segment = str(raw_seg).strip() if raw_seg else None
    if expected_annual_turnover is None and isinstance(md0, dict):
        try:
            raw_e = md0.get("expected_annual_turnover")
            expected_annual_turnover = float(raw_e) if raw_e is not None else None
        except (TypeError, ValueError):
            pass

    assessment = await assess_transaction(
        txn_dict,
        baseline_txns=baseline,
        customer_profile={
            "role": "unknown",
            "customer_id": txn.customer_id,
            "customer_segment": kyc_segment,
            "expected_annual_turnover": expected_annual_turnover,
            "line_of_business": line_of_business,
        },
        skip_llm=skip_llm_effective,
    )
    profile_label = str(md0.get("profile") or md0.get("pattern") or "") if isinstance(md0, dict) else ""
    ytd_ngn = ytd_calendar_year_inflow_ngn(txn.customer_id, baseline, txn_dict)
    typ_hits = evaluate_typologies(
        txn_dict,
        baseline,
        customer_profile_label=profile_label,
        kyc_segment=kyc_segment,
        expected_annual_turnover=expected_annual_turnover,
        customer_remarks=customer_remarks,
        ytd_inflow_total_ngn=ytd_ngn,
        line_of_business=line_of_business,
    )

    cp_name = str(txn_dict.get("counterparty_name") or md0.get("counterparty_name") or "").strip()
    if _is_inflow(txn_dict) and len(cp_name) >= 3:
        from app.services.reference_lists_service import screen_customer_name

        cps = screen_customer_name(cp_name)
        if cps.get("sanctions"):
            typ_hits.append(
                TypologyHit(
                    rule_id="TYP-COUNTERPARTY-REF-SANCTIONS",
                    title="Counterparty matches internal reference sanctions list (fuzzy)",
                    narrative=(
                        f"The counterparty name “{cp_name}” fuzzy-matched uploaded sanctions reference data "
                        f"(threshold {cps.get('fuzzy_threshold')})."
                    ),
                    nfiu_reference="Sanctions / high-risk jurisdiction",
                )
            )
        if cps.get("pep"):
            typ_hits.append(
                TypologyHit(
                    rule_id="TYP-COUNTERPARTY-REF-PEP",
                    title="Counterparty matches internal PEP reference list (fuzzy)",
                    narrative=(
                        f"The counterparty name “{cp_name}” fuzzy-matched uploaded PEP reference data "
                        f"(threshold {cps.get('fuzzy_threshold')})."
                    ),
                    nfiu_reference="PEP",
                )
            )

    if not skip_llm_effective:
        ai_hits = await run_realtime_ai_transaction_screening(
            txn_dict,
            kyc_context={
                "customer_segment": kyc_segment or "",
                "expected_annual_turnover": expected_annual_turnover,
                "line_of_business": line_of_business or "",
                "customer_remarks": customer_remarks or "",
            },
            baseline_inflow_count=len([t for t in baseline if _is_inflow(t)]),
            ytd_inflow_total=ytd_ngn,
            existing_rule_ids=[h.rule_id for h in typ_hits],
        )
        typ_hits = dedupe_typology_hits(list(typ_hits) + list(ai_hits))

    rf_hits = await evaluate_custom_red_flags(
        pg,
        txn_dict,
        customer_remarks=customer_remarks or "",
        line_of_business=line_of_business or "",
    )
    typ_hits = dedupe_typology_hits(list(typ_hits) + list(rf_hits))

    def _pattern_red_flag_codes(hits_list: List[TypologyHit]) -> List[str]:
        out: List[str] = []
        for h in hits_list:
            rid = h.rule_id
            if not rid.startswith("RF-") or rid.startswith("RF-AI-"):
                continue
            out.append(rid[3:])
        return out

    llm_rf_hits: List[TypologyHit] = []
    if not skip_llm_effective:
        llm_rf_hits = await run_red_flag_llm_matcher(
            pg,
            txn_dict,
            baseline,
            customer_id=txn.customer_id,
            customer_remarks=customer_remarks or "",
            line_of_business=line_of_business or "",
            kyc_segment=kyc_segment or "",
            expected_annual_turnover=expected_annual_turnover,
            customer_name=customer_name,
            pattern_matched_rule_codes=_pattern_red_flag_codes(rf_hits),
            transaction_id=str(txn_dict.get("id") or txn_id),
        )
    typ_hits = dedupe_typology_hits(list(typ_hits) + list(llm_rf_hits))

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
        demo_sv = md0.get("demo_severity")
        if demo_sv is not None:
            try:
                dv = float(demo_sv)
                if 0.0 <= dv <= 1.0:
                    severity = max(severity, min(0.96, dv))
            except (TypeError, ValueError):
                pass
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
    request: Request,
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
    _persist_txn_geo(txn)
    background.add_task(_process_transaction_async, txn.id, request.app.state.pg)
    return txn


@router.post("/bulk-ingest")
async def bulk_ingest(
    request: Request,
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
            _persist_txn_geo(txn)
            await _process_transaction_async(txn.id, request.app.state.pg)
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
    if not txn or not _txn_not_soft_deleted(txn):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    _persist_txn_geo(txn)
    txn = _TXNS.get(transaction_id)
    if not txn_matches_user_scope(user, txn.metadata, txn.customer_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transaction outside your zone/branch scope.")
    return txn


def _txn_day(t: TransactionResponse) -> date:
    ca = t.created_at
    if isinstance(ca, datetime):
        return ca.date()
    return date.today()


@router.get("/", response_model=Dict[str, Any])
async def list_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    entity_id: Optional[str] = Query(None, description="Substring match on customer_id"),
    transaction_type: Optional[str] = None,
    q: Optional[str] = Query(None, description="Search id, customer, type, narrative"),
    user: Dict[str, Any] = Depends(get_current_user),
):
    for t in _TXNS.values():
        _persist_txn_geo(t)
    items = [
        t
        for t in _TXNS.values()
        if txn_matches_user_scope(user, t.metadata, t.customer_id) and _txn_not_soft_deleted(t)
    ]
    if status_filter:
        items = [t for t in items if t.status == status_filter]
    if min_amount is not None:
        items = [t for t in items if t.amount >= min_amount]
    if max_amount is not None:
        items = [t for t in items if t.amount <= max_amount]
    if entity_id and str(entity_id).strip():
        needle = str(entity_id).strip().lower()
        items = [t for t in items if needle in (t.customer_id or "").lower()]
    if transaction_type and str(transaction_type).strip():
        tt = str(transaction_type).strip().lower()
        items = [t for t in items if (t.transaction_type or "").lower() == tt]
    if q and str(q).strip():
        ql = str(q).strip().lower()
        items = [
            t
            for t in items
            if ql in (t.id or "").lower()
            or ql in (t.customer_id or "").lower()
            or ql in (t.transaction_type or "").lower()
            or ql in (t.narrative or "").lower()
        ]
    sd = (start_date or "").strip()[:10]
    ed = (end_date or "").strip()[:10]
    if sd:
        try:
            d0 = datetime.fromisoformat(sd).date()
            items = [t for t in items if _txn_day(t) >= d0]
        except Exception:
            pass
    if ed:
        try:
            d1 = datetime.fromisoformat(ed).date()
            items = [t for t in items if _txn_day(t) <= d1]
        except Exception:
            pass

    items.sort(key=lambda t: t.created_at if isinstance(t.created_at, datetime) else datetime.min, reverse=True)

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    return {"items": page_items, "total": total, "page": page, "page_size": page_size, "skip": start, "limit": page_size}


@router.get("/{transaction_id}/graph", response_model=GraphResponse)
async def get_transaction_graph(
    transaction_id: str,
    depth: int = Query(2, ge=1, le=3),
    user: Dict[str, Any] = Depends(get_current_user),
) -> GraphResponse:
    txn = _TXNS.get(transaction_id)
    if not txn or not _txn_not_soft_deleted(txn):
        raise HTTPException(status_code=404, detail="Transaction not found")
    # Minimal graph response for UI: one node.
    return GraphResponse(nodes=[{"id": txn.id, "type": "transaction", "properties": txn.model_dump()}], edges=[])


@router.post("/{transaction_id}/analyze")
async def analyze_transaction(
    request: Request,
    transaction_id: str,
    background: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if transaction_id not in _TXNS:
        raise HTTPException(status_code=404, detail="Transaction not found")
    background.add_task(_process_transaction_async, transaction_id, request.app.state.pg)
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

