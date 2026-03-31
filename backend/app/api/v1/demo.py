from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.v1.transactions import (  # type: ignore[attr-defined]
    _TXNS,
    _process_transaction_async,
    run_temporal_simulation,
)
from app.config import settings
from app.core.security import create_access_token, get_current_user
from app.models.transaction import TransactionResponse
from app.services.customer_kyc_db import clear_memory_kyc

router = APIRouter(prefix="/demo")


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


async def _clear_demo_stores(request: Request, *, clear_postgres_kyc: bool) -> None:
    _TXNS.clear()
    from app.api.v1.alerts import _ALERTS

    _ALERTS.clear()
    from app.api.v1.reports import _REPORTS

    _REPORTS.clear()
    clear_memory_kyc()

    if clear_postgres_kyc:
        pg = getattr(request.app.state, "pg", None)
        if pg is not None:
            try:
                await pg.execute("DELETE FROM aml_customer_kyc")
            except Exception:
                pass


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
        await _clear_demo_stores(request, clear_postgres_kyc=body.clear_postgres_kyc)

    now = datetime.utcnow()
    created: List[str] = []

    def q(txn: TransactionResponse) -> None:
        created.append(txn.id)

    # --- Baseline: civil servant IPPIS pattern (Lagos) ---
    t0 = TransactionResponse(
        id=str(uuid4()),
        customer_id="DEMO-PERSON-ADESANYA",
        amount=285_430.50,
        currency="NGN",
        transaction_type="salary",
        narrative="IPPIS salary credit — Federal Ministry of Finance (September)",
        counterparty_id="NIP-FGN-IPPIS",
        counterparty_name="Office of the Accountant-General of the Federation",
        status="posted",
        created_at=now - timedelta(days=45),
        metadata=_md(
            profile="civil_servant_ippis",
            sender_bank="Central Bank of Nigeria / IPPIS",
            pattern="recurring_salary",
        ),
    )
    await _enqueue(t0)
    q(t0)

    t1 = TransactionResponse(
        id=str(uuid4()),
        customer_id="DEMO-PERSON-ADESANYA",
        amount=18_750.00,
        currency="NGN",
        transaction_type="transfer_in",
        narrative="NIP in — wife allowance (GTBank)",
        counterparty_id="CP-WIFE-GTB",
        counterparty_name="Mrs. Adesanya Omolara",
        status="posted",
        created_at=now - timedelta(days=12),
        metadata=_md(profile="civil_servant_ippis", sender_bank="GTBank Plc"),
    )
    await _enqueue(t1)
    q(t1)

    # --- Flagship wire vs salary profile (triggers anomaly + typology) ---
    wire = TransactionResponse(
        id=str(uuid4()),
        customer_id="DEMO-PERSON-ADESANYA",
        amount=42_500_000.00,
        currency="NGN",
        transaction_type="wire",
        narrative="SWIFT inflow — Dubai Metals Trading FZ-LLC ref contract DM-2025-881 (gov ministry mentioned in cover)",
        counterparty_id="AE-DUBAI-METALS",
        counterparty_name="Dubai Metals Trading FZ-LLC",
        status="posted",
        created_at=now - timedelta(hours=6),
        metadata=_md(
            profile="civil_servant_ippis",
            sender_bank="Emirates NBD",
            counterparty_type="company",
            simulation_scenario="WIRE_SPIKE_DEMO",
        ),
    )
    await _enqueue(wire)
    q(wire)

    # --- Student smurfing / fan-in (UNILAG) ---
    start_fan = now - timedelta(hours=2)
    for i in range(1, 14):
        txn = TransactionResponse(
            id=str(uuid4()),
            customer_id="DEMO-PERSON-OKAFOR-UNILAG",
            amount=285_000 + i * 4_200,
            currency="NGN",
            transaction_type="transfer_in",
            narrative=f"UBA NIP credit — uncle segment {i} (family support)",
            counterparty_id=f"CP-RELATIVE-{i:02d}",
            counterparty_name=f"Okafor Relative {i}",
            status="posted",
            created_at=start_fan + timedelta(minutes=5 * i),
            metadata=_md(
                profile="student_unilag_low_income",
                sender_bank="United Bank for Africa",
                pattern="smurfing_demo",
            ),
        )
        await _enqueue(txn)
        q(txn)

    # --- Tailor profile vs implausible business narration ---
    tailor = TransactionResponse(
        id=str(uuid4()),
        customer_id="DEMO-PERSON-NWOSU-TAILOR",
        amount=38_900_000.00,
        currency="NGN",
        transaction_type="transfer_in",
        narrative="Payment — Lekki Phase 1 solar installation and inverter supply (building contract phase 2)",
        counterparty_id="CP-SOLAR-LEKKI",
        counterparty_name="BrightGrid Solar Nigeria Ltd",
        status="posted",
        created_at=now - timedelta(hours=20),
        metadata=_md(
            profile="tailor_yaba_market",
            sender_bank="Stanbic IBTC",
            counterparty_type="company",
        ),
    )
    await _enqueue(tailor)
    q(tailor)

    # --- Layering trader (Aba) ---
    layer_in = TransactionResponse(
        id=str(uuid4()),
        customer_id="DEMO-PERSON-IBE-ABA",
        amount=22_400_000.00,
        currency="NGN",
        transaction_type="transfer_in",
        narrative="Inflow — Onitsha market goods consolidation (Ecobank)",
        counterparty_id="CP-ONITSHA-AGG",
        counterparty_name="Eze & Sons Commodities",
        status="posted",
        created_at=now - timedelta(minutes=95),
        metadata=_md(profile="sme_fabric_trader", sender_bank="Ecobank Nigeria"),
    )
    await _enqueue(layer_in)
    q(layer_in)
    layer_out1 = TransactionResponse(
        id=str(uuid4()),
        customer_id="DEMO-PERSON-IBE-ABA",
        amount=21_100_000.00,
        currency="NGN",
        transaction_type="transfer_out",
        narrative="Outward — Zenith Kano distributor settlement",
        counterparty_id="CP-KANO-DIST",
        counterparty_name="Ibrahim Distributors Kano",
        status="posted",
        created_at=now - timedelta(minutes=78),
        metadata=_md(profile="sme_fabric_trader", sender_bank="Zenith Bank"),
    )
    await _enqueue(layer_out1)
    q(layer_out1)
    layer_out2 = TransactionResponse(
        id=str(uuid4()),
        customer_id="DEMO-PERSON-IBE-ABA",
        amount=1_050_000.00,
        currency="NGN",
        transaction_type="transfer_out",
        narrative="Wallet sweep — Opay business account",
        counterparty_id="OPAY-WALLET",
        counterparty_name="Opay Digital Services",
        status="posted",
        created_at=now - timedelta(minutes=70),
        metadata=_md(profile="sme_fabric_trader", channel="wallet", sender_bank="Opay"),
    )
    await _enqueue(layer_out2)
    q(layer_out2)

    # --- Structuring-style cash (same student) ---
    for i, amt in enumerate((980_000, 995_000, 990_000), start=1):
        c = TransactionResponse(
            id=str(uuid4()),
            customer_id="DEMO-PERSON-OKAFOR-UNILAG",
            amount=float(amt),
            currency="NGN",
            transaction_type="cash_deposit",
            narrative=f"Cash lodgment UNILAG branch — tranche {i} (teller receipt)",
            status="posted",
            created_at=now - timedelta(days=1, hours=i),
            metadata=_md(profile="student_unilag_low_income", pattern="structuring_demo", sequence=i),
        )
        await _enqueue(c)
        q(c)

    # --- Crypto keyword + individual payroll-style narration ---
    crypto_ref = TransactionResponse(
        id=str(uuid4()),
        customer_id="DEMO-PERSON-BALOGUN-RETAIL",
        amount=6_200_000.00,
        currency="NGN",
        transaction_type="transfer_in",
        narrative="USDT settlement — Binance P2P ref (staff salary batch for shop assistants)",
        counterparty_id="CP-P2P-REF",
        counterparty_name="P2P Merchant Lagos",
        status="posted",
        created_at=now - timedelta(hours=14),
        metadata=_md(
            profile="individual_retail_account",
            account_class="individual",
            sender_bank="Providus Bank",
        ),
    )
    await _enqueue(crypto_ref)
    q(crypto_ref)

    # --- Corporate-style inflow to individual ---
    corp_ind = TransactionResponse(
        id=str(uuid4()),
        customer_id="DEMO-PERSON-EZE-INDIV",
        amount=15_000_000.00,
        currency="NGN",
        transaction_type="transfer_in",
        narrative="Inflow from Dangote Cement Plc — alleged staff bonus (unverified)",
        counterparty_id="RC-DANGOTE",
        counterparty_name="Dangote Cement Plc",
        status="posted",
        created_at=now - timedelta(hours=30),
        metadata=_md(
            profile="individual_sme",
            counterparty_type="company",
            customer_segment="retail",
            sender_bank="Access Bank",
        ),
    )
    await _enqueue(corp_ind)
    q(corp_ind)

    return {"seeded_transactions": len(created), "transaction_ids": created, "replaced": body.replace_existing}


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
        await _clear_demo_stores(request, clear_postgres_kyc=body.clear_postgres_kyc)

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
    return await run_temporal_simulation(
        years=body.years,
        seed=body.seed,
        clear_existing=body.clear_existing,
        max_transactions=body.max_transactions,
        refit_every=body.refit_every,
    )
