"""
Shared definitions for POST /demo/seed standard AML transaction pack.

Keeps Excel export and live seeding aligned via run_standard_demo_transaction_sequence().
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Dict
from uuid import uuid4

from app.models.transaction import TransactionResponse

EmitFn = Callable[[TransactionResponse], Awaitable[None]]


def _md(**kwargs: Any) -> Dict[str, Any]:
    return dict(kwargs)


async def run_standard_demo_transaction_sequence(now: datetime, emit: EmitFn) -> None:
    """Build the standard demo transactions (same order as POST /demo/seed)."""

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
    await emit(t0)

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
    await emit(t1)

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
    await emit(wire)

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
        await emit(txn)

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
    await emit(tailor)

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
    await emit(layer_in)
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
    await emit(layer_out1)
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
    await emit(layer_out2)

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
        await emit(c)

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
    await emit(crypto_ref)

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
    await emit(corp_ind)
