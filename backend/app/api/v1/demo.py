from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.api.v1.transactions import _TXNS, _process_transaction_async  # type: ignore[attr-defined]
from app.core.security import get_current_user
from app.models.transaction import TransactionResponse

router = APIRouter(prefix="/demo")


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

