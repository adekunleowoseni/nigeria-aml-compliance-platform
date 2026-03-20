from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.v1.transactions import (  # type: ignore[attr-defined]
    _TXNS,
    _process_transaction_async,
    run_temporal_simulation,
)
from app.config import settings
from app.core.security import create_access_token, get_current_user
from app.models.transaction import TransactionResponse

router = APIRouter(prefix="/demo")


class SimulateTemporalBody(BaseModel):
    """Multi-year synthetic history for customer-specific pattern learning."""

    years: int = Field(10, ge=1, le=30, description="Calendar span of simulated history")
    seed: int = Field(42, description="RNG seed for reproducible runs")
    clear_existing: bool = Field(True, description="Clear in-memory txns/alerts before simulating")
    max_transactions: int = Field(100_000, ge=5_000, le=500_000, description="Hard cap on generated rows")
    refit_every: int = Field(500, ge=50, le=5_000, description="Refit Isolation Forest every N prior txns per customer")


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


@router.post("/seed")
async def seed_demo_data(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Seed in‑memory demo data for multiple AML scenarios.

    This does NOT touch Postgres; it only populates the in‑memory Transaction store
    so that the dashboard and anomaly/AI pipeline can be exercised end‑to‑end.
    """
    now = datetime.utcnow()
    created: List[str] = []

    # Baseline "normal" salary customer
    baseline_txn = TransactionResponse(
        id=str(uuid4()),
        customer_id="CUST-NG-1001",
        amount=250_000,
        currency="NGN",
        transaction_type="salary",
        status="posted",
        created_at=now - timedelta(days=30),
    )
    await _enqueue(baseline_txn)
    created.append(baseline_txn.id)

    # Scenario A: Smurfing / fan‑in to a student account
    start = now - timedelta(hours=1)
    for i in range(1, 16):
        txn = TransactionResponse(
            id=str(uuid4()),
            customer_id="CUST-NG-STUDENT",
            amount=300_000 + i * 5_000,
            currency="NGN",
            transaction_type="transfer_in",
            status="posted",
            created_at=start + timedelta(minutes=4 * i),
        )
        await _enqueue(txn)
        created.append(txn.id)

    # Scenario B: Layering / pass‑through via SME trader
    layer_in = TransactionResponse(
        id=str(uuid4()),
        customer_id="CUST-NG-TRADER",
        amount=5_000_000,
        currency="NGN",
        transaction_type="transfer_in",
        status="posted",
        created_at=now - timedelta(minutes=50),
    )
    layer_out1 = TransactionResponse(
        id=str(uuid4()),
        customer_id="CUST-NG-TRADER",
        amount=4_800_000,
        currency="NGN",
        transaction_type="transfer_out",
        status="posted",
        created_at=now - timedelta(minutes=40),
    )
    layer_out2 = TransactionResponse(
        id=str(uuid4()),
        customer_id="CUST-NG-TRADER",
        amount=150_000,
        currency="NGN",
        transaction_type="transfer_out",
        status="posted",
        created_at=now - timedelta(minutes=35),
    )
    for t in (layer_in, layer_out1, layer_out2):
        await _enqueue(t)
        created.append(t.id)

    # Scenario C: Unusual cash deposits vs profile
    cash1 = TransactionResponse(
        id=str(uuid4()),
        customer_id="CUST-NG-STUDENT",
        amount=2_000_000,
        currency="NGN",
        transaction_type="cash_deposit",
        status="posted",
        created_at=now - timedelta(days=2),
    )
    cash2 = TransactionResponse(
        id=str(uuid4()),
        customer_id="CUST-NG-STUDENT",
        amount=1_800_000,
        currency="NGN",
        transaction_type="cash_deposit",
        status="posted",
        created_at=now - timedelta(days=2, hours=1),
    )
    for t in (cash1, cash2):
        await _enqueue(t)
        created.append(t.id)

    return {"seeded_transactions": len(created), "transaction_ids": created}


@router.post("/simulate-temporal")
async def simulate_temporal(body: SimulateTemporalBody, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Generate ~N years of synthetic transactions per customer profile, inject AML scenarios
    (smurfing, layering, structuring, velocity, wire spikes, round-trips, etc.), then score
    each event against **that customer's** prior history so Isolation Forest learns normal patterns.
    """
    return await run_temporal_simulation(
        years=body.years,
        seed=body.seed,
        clear_existing=body.clear_existing,
        max_transactions=body.max_transactions,
        refit_every=body.refit_every,
    )

