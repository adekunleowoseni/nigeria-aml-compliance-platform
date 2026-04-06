from __future__ import annotations

import csv
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.api.v1.in_memory_stores import _ALERTS, _TXNS
from app.api.v1.transactions import _process_transaction_async, run_temporal_simulation
from app.config import settings
from app.core.security import create_access_token, get_current_user
from app.services import audit_trail
from app.models.transaction import TransactionResponse
from app.services.aop_upload_store import clear_aop_upload_catalog
from app.services.customer_kyc_db import clear_memory_kyc
from app.services.demo_showcase import seed_high_risk_showcase
from app.services.demo_seed_export import build_demo_seed_workbook_bytes
from app.services.demo_standard_seed import run_standard_demo_transaction_sequence
from app.services.otc_branch_reference_seed import apply_otc_branch_reference_seed, export_reference_table_json_ready
from app.services.demo_aop_template_seed import seed_demo_aop_template_for_all_customers

router = APIRouter(prefix="/demo")


async def _attach_demo_aop_templates(request: Request, user: Dict[str, Any]) -> Dict[str, Any]:
    email = user.get("email") or user.get("sub")
    em = email.strip()[:320] if isinstance(email, str) and email.strip() else None
    return await seed_demo_aop_template_for_all_customers(request, uploaded_by_email=em)


class SimulateTemporalBody(BaseModel):
    """Multi-year synthetic history for customer-specific pattern learning."""

    years: int = Field(10, ge=1, le=30, description="Calendar span of simulated history")
    seed: int = Field(42, description="RNG seed for reproducible runs")
    clear_existing: bool = Field(True, description="Clear in-memory txns/alerts/reports before simulating")
    clear_postgres_kyc: bool = Field(
        True,
        description="DELETE FROM aml_customer_kyc when clearing (Postgres connected)",
    )
    max_transactions: int = Field(100_000, ge=5_000, le=500_000, description="Hard cap on generated rows")
    refit_every: int = Field(500, ge=50, le=5_000, description="Refit Isolation Forest every N prior txns per customer")


class SeedDemoBody(BaseModel):
    """Replace all in-memory AML demo data with a fresh realistic scenario pack."""

    replace_existing: bool = Field(True, description="Clear txns, alerts, reports, and KYC memory before seeding")
    clear_postgres_kyc: bool = Field(
        True,
        description="DELETE FROM aml_customer_kyc when Postgres is available (fresh STR/KYC demo rows)",
    )


class IngestFlagshipBody(BaseModel):
    replace_existing: bool = Field(True, description="Clear demo stores before inserting the flagship txn")
    clear_postgres_kyc: bool = Field(True, description="Truncate aml_customer_kyc when connected")


class ShowcaseSeedBody(BaseModel):
    """Twelve high-risk typology tracks (80–96% severity targets) for demos and training."""

    replace_existing: bool = Field(True, description="Clear txns, alerts, reports before seeding showcase")
    clear_postgres_kyc: bool = Field(
        True,
        description="DELETE FROM aml_customer_kyc when Postgres is available",
    )


class OtcBranchReferenceSeedBody(BaseModel):
    """Load the 10-row branch OTC intake table (3 cash / ESTR + 7 identity / ESAR) into demo stores."""

    replace_existing: bool = Field(
        False,
        description="Clear txns, alerts, reports, and KYC memory (optional Postgres) before loading",
    )
    clear_postgres_kyc: bool = Field(
        False,
        description="When replace_existing, DELETE FROM aml_customer_kyc when Postgres is connected",
    )
    cco_pre_approve: bool = Field(
        False,
        description="If true, seed rows are escalated + CCO OTC-approved (instant report eligibility). Default false = full CO escalate → CCO approve workflow.",
    )


async def _clear_demo_stores(
    request: Request,
    *,
    clear_postgres_kyc: bool,
    user: Optional[Dict[str, Any]] = None,
    context: str = "demo",
) -> None:
    _TXNS.clear()
    _ALERTS.clear()
    from app.api.v1.reports import _REPORTS

    _REPORTS.clear()
    clear_memory_kyc()
    pg = getattr(request.app.state, "pg", None)
    if pg is not None:
        try:
            from app.services.aop_upload_db import delete_all_aop_upload_rows

            await delete_all_aop_upload_rows(pg)
        except Exception:
            pass
    clear_aop_upload_catalog()

    if clear_postgres_kyc:
        if pg is not None:
            try:
                await pg.execute("DELETE FROM aml_customer_kyc")
            except Exception:
                pass
    if user:
        audit_trail.record_event_from_user(
            user,
            action="demo.stores_cleared",
            resource_type="demo_environment",
            resource_id=context,
            details={"clear_postgres_kyc": clear_postgres_kyc, "context": context},
        )


@router.get("/token")
def get_demo_token() -> Dict[str, str]:
    """
    Dev-only: return a JWT for the demo user so the frontend can call protected APIs.
    Only available when APP_ENV=development.
    """
    if settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Not available")
    token = create_access_token("demo-user", extra={"role": "compliance_officer"})
    return {"access_token": token, "token_type": "bearer"}


async def _enqueue(txn: TransactionResponse) -> None:
    _TXNS[txn.id] = txn
    await _process_transaction_async(txn.id)


def _md(**kwargs: Any) -> Dict[str, Any]:
    return dict(kwargs)


@router.post("/seed")
async def seed_demo_data(
    request: Request,
    body: SeedDemoBody = SeedDemoBody(),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Replace demo data with realistic Nigerian-style names, counterparties, and AML scenarios.
    """
    if body.replace_existing:
        await _clear_demo_stores(
            request,
            clear_postgres_kyc=body.clear_postgres_kyc,
            user=user,
            context="seed",
        )

    now = datetime.utcnow()
    acc: List[TransactionResponse] = []

    async def emit(txn: TransactionResponse) -> None:
        acc.append(txn)
        await _enqueue(txn)

    await run_standard_demo_transaction_sequence(now, emit)
    created = [t.id for t in acc]

    aop_seed = await _attach_demo_aop_templates(request, user)
    return {
        "seeded_transactions": len(created),
        "transaction_ids": created,
        "replaced": body.replace_existing,
        "aop_template_seed": aop_seed,
    }


@router.post("/seed-showcase")
async def seed_showcase_high_risk(
    request: Request,
    body: ShowcaseSeedBody = ShowcaseSeedBody(),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Load twelve synthetic AML scenario tracks (PEP, mole pass-through, hub fan-out, identical narrations,
    terrorism/proliferation wording, tax-evasion indicators, structuring, rapid in/out, crypto, ransom wording,
    government-themed embezzlement narrative, SAR-style composite). Amounts are large; alert severity is floored
    via metadata.demo_severity (0.80–0.96) where needed. All synthetic — not real events.
    """
    if body.replace_existing:
        await _clear_demo_stores(
            request,
            clear_postgres_kyc=body.clear_postgres_kyc,
            user=user,
            context="seed_showcase",
        )
    out = await seed_high_risk_showcase(_enqueue, now=datetime.utcnow())
    out["replaced"] = body.replace_existing
    out["aop_template_seed"] = await _attach_demo_aop_templates(request, user)
    return out


@router.post("/seed-otc-branch-reference")
async def seed_otc_branch_reference(
    request: Request,
    body: OtcBranchReferenceSeedBody = OtcBranchReferenceSeedBody(),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Seed transactions, alerts, and KYC from a fixed branch STR / OTC intake spreadsheet (Apr 2026 sample).

    **OTC ESTR (cash):** reference STR IDs 14320, 14295, 14318 — default seed leaves matters **open** until CO escalates and
    CCO approves OTC reporting; set ``cco_pre_approve=true`` to skip that for demos.

    **OTC ESAR (identity):** the other seven rows — same escalation + CCO OTC approval, then **Generate OTC ESAR** on Reports.
    """
    if body.replace_existing:
        await _clear_demo_stores(
            request,
            clear_postgres_kyc=body.clear_postgres_kyc,
            user=user,
            context="seed_otc_branch_reference",
        )
    out = await apply_otc_branch_reference_seed(request, cco_pre_approve=body.cco_pre_approve)
    out["replaced"] = body.replace_existing
    out["aop_template_seed"] = await _attach_demo_aop_templates(request, user)
    return out


@router.post("/seed-complete-demo")
async def seed_complete_demo(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Single action: clear demo stores once, then load (1) standard AML demo pack, (2) twelve-track high-risk showcase,
    (3) branch OTC / STR reference spreadsheet (10 rows), (4) attach demo AOP templates, and (5) append **10-year
    synthetic history** for the six temporal demo profiles (baseline + scenarios + integration legs) **without** wiping
    the prior seeds — same net effect as the former standalone "Simulate 10-year history" after the packs above.

    May take 1–2 minutes. Postgres ``aml_customer_kyc`` is cleared at the start (same as before).
    """
    await _clear_demo_stores(
        request,
        clear_postgres_kyc=True,
        user=user,
        context="seed_complete_demo",
    )
    standard = await seed_demo_data(
        request,
        SeedDemoBody(replace_existing=False, clear_postgres_kyc=False),
        user,
    )
    showcase = await seed_showcase_high_risk(
        request,
        ShowcaseSeedBody(replace_existing=False, clear_postgres_kyc=False),
        user,
    )
    otc = await seed_otc_branch_reference(
        request,
        OtcBranchReferenceSeedBody(replace_existing=False, clear_postgres_kyc=False),
        user,
    )
    otc_txn = otc.get("transaction_ids") if isinstance(otc.get("transaction_ids"), list) else []
    aop_final = await _attach_demo_aop_templates(request, user)
    temporal = await run_temporal_simulation(
        years=10,
        seed=42,
        clear_existing=False,
        max_transactions=100_000,
        refit_every=500,
    )
    audit_trail.record_event_from_user(
        user,
        action="demo.seed_complete_demo",
        resource_type="demo_environment",
        resource_id="seed_complete_demo",
        details={
            "temporal_transactions": temporal.get("total_generated"),
            "temporal_alerts": temporal.get("alerts_created"),
        },
    )
    return {
        "cleared": True,
        "standard": standard,
        "showcase": showcase,
        "otc_branch": otc,
        "aop_template_seed": aop_final,
        "temporal_simulation": temporal,
        "seeded_transactions_total": int(standard.get("seeded_transactions") or 0)
        + int(showcase.get("seeded_transactions") or 0)
        + len(otc_txn)
        + int(temporal.get("total_generated") or 0),
        "in_memory_transaction_count": len(_TXNS),
    }


@router.get("/otc-branch-reference-table")
def get_otc_branch_reference_table(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Return the reference spreadsheet as structured JSON (no DB write)."""
    _ = user
    rows = export_reference_table_json_ready()
    return {"rows": rows, "count": len(rows)}


@router.get("/otc-branch-reference-table/export")
def export_otc_branch_reference_table(
    user: Dict[str, Any] = Depends(get_current_user),
    format: str = "csv",
):
    """
    Download the branch OTC / STR **reference** demo rows as a file (opens in Excel).

    Source is the same logical table as ``POST /demo/seed-otc-branch-reference`` — not live in-memory data.
    Use ``format=csv`` (default). UTF-8 with BOM for Windows Excel.
    """
    _ = user
    fmt = (format or "csv").strip().lower()
    if fmt != "csv":
        raise HTTPException(status_code=400, detail="Only format=csv is supported")
    rows = export_reference_table_json_ready()
    if not rows:
        raise HTTPException(status_code=404, detail="No reference rows")
    buf = StringIO()
    fieldnames = list(rows[0].keys())
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        flat = {k: r.get(k) if r.get(k) is not None else "" for k in fieldnames}
        w.writerow(flat)
    body = buf.getvalue().encode("utf-8-sig")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="otc-branch-reference-demo-structure.csv"'
        },
    )


@router.get("/export-all-seed-data")
async def export_all_seed_data_xlsx(user: Dict[str, Any] = Depends(get_current_user)) -> StreamingResponse:
    """
    Download a multi-sheet Excel workbook of static demo seed/reference data (OTC table, standard seed,
    showcase tracks, flagship ingest template, temporal profiles and scenario codes). Does not modify stores.
    """
    _ = user
    data = await build_demo_seed_workbook_bytes()
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="nigeria-aml-demo-seed-data.xlsx"'},
    )


@router.post("/ingest-flagship")
async def ingest_flagship_suspicious_txn(
    request: Request,
    body: IngestFlagshipBody = IngestFlagshipBody(),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Clear demo stores (optional) and ingest one high-signal suspicious transaction for quick testing.
    """
    if body.replace_existing:
        await _clear_demo_stores(
            request,
            clear_postgres_kyc=body.clear_postgres_kyc,
            user=user,
            context="ingest_flagship",
        )

    now = datetime.utcnow()
    txn = TransactionResponse(
        customer_id="DEMO-PERSON-ADESANYA",
        amount=55_000_000.00,
        currency="NGN",
        transaction_type="wire",
        narrative=(
            "FCMB SWIFT — Federal Ministry of Works refund referenced in memo; "
            "beneficiary individual salary account (PEP-style review required)"
        ),
        counterparty_id="NG-FMW-REFUND",
        counterparty_name="Federal Ministry of Works & Housing",
        status="received",
        created_at=now,
        metadata=_md(
            profile="civil_servant_ippis",
            sender_bank="First City Monument Bank",
            pep_flag=True,
            counterparty_type="government_entity",
            simulation_scenario="FLAGSHIP_DEMO",
        ),
    )
    await _enqueue(txn)
    return {"transaction_id": txn.id, "replaced": body.replace_existing}


@router.post("/simulate-temporal")
async def simulate_temporal(
    request: Request,
    body: SimulateTemporalBody,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Generate ~N years of synthetic transactions per customer profile, inject AML scenarios
    (smurfing, layering, structuring, velocity, wire spikes, round-trips, etc.), then score
    each event against **that customer's** prior history so Isolation Forest learns normal patterns.
    """
    if body.clear_existing and body.clear_postgres_kyc:
        pg = getattr(request.app.state, "pg", None)
        if pg is not None:
            try:
                await pg.execute("DELETE FROM aml_customer_kyc")
            except Exception:
                pass
    out = await run_temporal_simulation(
        years=body.years,
        seed=body.seed,
        clear_existing=body.clear_existing,
        max_transactions=body.max_transactions,
        refit_every=body.refit_every,
    )
    if body.clear_existing:
        audit_trail.record_event_from_user(
            user,
            action="demo.temporal_simulation_cleared",
            resource_type="demo_environment",
            resource_id="simulate_temporal",
            details={
                "clear_postgres_kyc": body.clear_postgres_kyc,
                "years": body.years,
                "seed": body.seed,
            },
        )
    return out
