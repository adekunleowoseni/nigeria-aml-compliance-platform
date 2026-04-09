"""
Bulk synthetic transactions for statement-of-account demos: NIBSS/NIP, card, POS, USSD,
and other inflows/outflows across all demo customers. Scenario customers (DEMO-SC-*) also
receive suspicious outflow legs (structuring-style splits, internal/external drains).
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Dict, List
from uuid import uuid4

from app.models.transaction import TransactionResponse

EmitFn = Callable[[TransactionResponse], Awaitable[None]]

# Standard pack + showcase scenario tracks + temporal simulation profiles
ALL_DEMO_CUSTOMER_IDS: tuple[str, ...] = (
    "DEMO-PERSON-ADESANYA",
    "DEMO-PERSON-OKAFOR-UNILAG",
    "DEMO-PERSON-NWOSU-TAILOR",
    "DEMO-PERSON-IBE-ABA",
    "DEMO-PERSON-BALOGUN-RETAIL",
    "DEMO-PERSON-EZE-INDIV",
    "DEMO-SC-PEP",
    "DEMO-SC-MOLE",
    "DEMO-SC-HUB",
    "DEMO-SC-TERROR",
    "DEMO-SC-TAX",
    "DEMO-SC-STRUCT",
    "DEMO-SC-IO",
    "DEMO-SC-CRYPTO",
    "DEMO-SC-RANSOM",
    "DEMO-SC-EMBEZ",
    "DEMO-SC-SAR",
    "DEMO-WORKER-LAGOS",
    "DEMO-STUDENT-UNILAG",
    "DEMO-TRADER-ABA",
    "DEMO-HNWI-VI",
    "DEMO-MERCHANT-OGBA",
    "DEMO-IMPORTER-APAPA",
)

SCENARIO_CUSTOMER_IDS: tuple[str, ...] = tuple(c for c in ALL_DEMO_CUSTOMER_IDS if c.startswith("DEMO-SC-"))

EXTERNAL_BANKS = (
    "Access Bank Plc",
    "GTBank Plc",
    "Zenith Bank Plc",
    "UBA Plc",
    "First Bank of Nigeria",
    "Fidelity Bank Plc",
    "Stanbic IBTC",
    "Union Bank of Nigeria",
    "Polaris Bank",
    "Wema Bank Plc",
)

INTERNAL_BRANCH_LABELS = (
    "Treasury pool — Lagos HQ",
    "Internal sweep — main operating account",
    "Staff suspense — branch 014",
    "NOSTRO settlement — Trade desk",
    "Related party current — group treasury",
)


def _md(**kwargs: Any) -> Dict[str, Any]:
    return dict(kwargs)


def _pick_when(rng: random.Random, base: datetime, *, days_back: int = 200) -> datetime:
    delta_days = rng.randint(1, days_back)
    delta_secs = rng.randint(0, 86400 - 1)
    return base - timedelta(days=delta_days, seconds=delta_secs)


def _build_routine_txn(
    rng: random.Random,
    now: datetime,
    customer_id: str,
    *,
    flavour: str,
) -> TransactionResponse:
    """Single routine statement line for ``flavour`` (channel/rail type)."""
    if flavour == "nip_in":
        tx_type = "transfer_in"
        amt = float(rng.randint(3_500, 2_400_000))
        narrative = (
            f"NIBSS Instant Pay (NIP) in — ref NIP/{rng.randint(100000, 999999)} "
            f"from {rng.choice(EXTERNAL_BANKS)}"
        )
        meta = _md(
            channel="nibss",
            payment_rail="NIP",
            direction="credit",
            statement_bucket="electronic_inflow",
            demo_statement_seed=True,
        )
        cp_name = rng.choice(EXTERNAL_BANKS) + " customer"
        cp_id = f"EXT-NIP-{rng.randint(10000, 99999)}"
    elif flavour == "nip_out":
        tx_type = "transfer_out"
        amt = float(rng.randint(2_000, 1_800_000))
        narrative = (
            f"NIBSS NIP out — beneficiary at {rng.choice(EXTERNAL_BANKS)} ref OUT-{rng.randint(8800000, 8899999)}"
        )
        meta = _md(
            channel="nibss",
            payment_rail="NIP",
            direction="debit",
            statement_bucket="electronic_outflow",
            demo_statement_seed=True,
        )
        cp_name = rng.choice(EXTERNAL_BANKS)
        cp_id = f"EXT-NIP-OUT-{rng.randint(10000, 99999)}"
    elif flavour == "nibss_collect":
        if rng.random() < 0.5:
            tx_type = "transfer_in"
            amt = float(rng.randint(10_000, 5_000_000))
            narrative = f"NIBSS collections — corporate sweep ref COL-{rng.randint(4100000, 4199999)}"
            meta = _md(
                channel="nibss",
                payment_rail="collections",
                statement_bucket="electronic_inflow",
                demo_statement_seed=True,
            )
            cp_id = f"COL-BATCH-{rng.randint(10000, 99999)}"
            cp_name = "Corporate collections"
        else:
            tx_type = "transfer_out"
            amt = float(rng.randint(15_000, 3_500_000))
            narrative = f"NIBSS outward clearing debit — settlement SB-{rng.randint(5500000, 5599999)}"
            meta = _md(
                channel="nibss",
                payment_rail="NIBSS_clearing",
                statement_bucket="electronic_outflow",
                demo_statement_seed=True,
            )
            cp_id = f"NCS-OUT-{rng.randint(100000, 999999)}"
            cp_name = rng.choice(EXTERNAL_BANKS)
    elif flavour == "card_settlement":
        tx_type = "transfer_in"
        amt = float(rng.randint(8_000, 950_000))
        narrative = (
            f"Card payment settlement — Paystack/ISW batch {rng.choice(['Verve', 'Visa', 'Mastercard'])} "
            f"merchant TID ***{rng.randint(1000, 9999)}"
        )
        meta = _md(
            channel="card",
            payment_rail="card_acquiring",
            pos_terminal_msk=f"****{rng.randint(1000, 9999)}",
            statement_bucket="card_inflow",
            demo_statement_seed=True,
        )
        cp_id = f"ACQ-{rng.choice(['PSK', 'ISW', 'ITX'])}-{rng.randint(100000, 999999)}"
        cp_name = "Acquirer settlement"
    elif flavour == "card_spend":
        tx_type = "transfer_out"
        amt = float(rng.randint(1_500, 420_000))
        narrative = (
            f"Debit card POS spend — {rng.choice(['Jumia', 'Slot', 'Shoprite', 'local merchant'])} "
            f"Lagos (terminal ref {rng.randint(100000, 999999)})"
        )
        meta = _md(
            channel="card",
            payment_rail="card_spend",
            statement_bucket="card_outflow",
            demo_statement_seed=True,
        )
        cp_id = f"MERCH-POS-{rng.randint(10000, 99999)}"
        cp_name = "Merchant acquirer"
    elif flavour == "pos_settlement":
        tx_type = "pos_settlement"
        amt = float(rng.randint(4_000, 1_200_000))
        narrative = (
            f"POS settlement in — Palmpay/Opay aggregator batch; agent ID {rng.randint(200000, 299999)}"
        )
        meta = _md(
            channel="pos",
            payment_rail="agent_banking",
            statement_bucket="pos_inflow",
            demo_statement_seed=True,
        )
        cp_id = f"AGG-POS-{rng.randint(100000, 999999)}"
        cp_name = rng.choice(["Palmpay Agency", "Moniepoint", "Opay Business"])
    elif flavour == "pos_spend":
        tx_type = "transfer_out"
        amt = float(rng.randint(2_000, 180_000))
        narrative = f"Agent POS cash-out / purchase — super agent corridor {rng.choice(['Ikeja', 'PH', 'Kano'])}"
        meta = _md(
            channel="pos",
            payment_rail="agent_pos",
            statement_bucket="pos_outflow",
            demo_statement_seed=True,
        )
        cp_id = f"AGT-{rng.randint(300000, 399999)}"
        cp_name = "Agent network"
    elif flavour == "ussd_in":
        tx_type = "transfer_in"
        amt = float(rng.randint(2_000, 350_000))
        narrative = f"USSD *{rng.choice(['919', '894', '322'])}# credit — mobile channel"
        meta = _md(
            channel="ussd",
            payment_rail="USSD",
            direction="credit",
            demo_statement_seed=True,
        )
        cp_id = f"USSD-{rng.randint(1000000, 9999999)}"
        cp_name = "USSD hub"
    elif flavour == "ussd_out":
        tx_type = "transfer_out"
        amt = float(rng.randint(1_500, 280_000))
        narrative = f"USSD transfer out — merchant payout ref {rng.randint(7700000, 7799999)}"
        meta = _md(
            channel="ussd",
            payment_rail="USSD",
            direction="debit",
            demo_statement_seed=True,
        )
        cp_id = f"USSD-{rng.randint(1000000, 9999999)}"
        cp_name = "USSD hub"
    elif flavour == "atm":
        tx_type = "cash_withdrawal"
        amt = float(rng.randint(5_000, 400_000))
        narrative = (
            f"ATM withdrawal — {rng.choice(['Onsite', 'Off-us'])} *{rng.randint(1000, 9999)} "
            f"{rng.choice(['Allen', 'Marina', 'VI', 'Wuse'])}"
        )
        meta = _md(
            channel="atm",
            payment_rail="ATM",
            statement_bucket="cash_out",
            demo_statement_seed=True,
        )
        cp_id = f"ATM-{rng.randint(10000, 99999)}"
        cp_name = "ATM switch"
    else:
        tx_type = "transfer_in"
        amt = float(rng.randint(5_000, 100_000))
        narrative = "Routine fee reversal / adjustment"
        meta = _md(channel="core_banking", demo_statement_seed=True)
        cp_id = "ADJ-SYS"
        cp_name = "Core banking"

    when = _pick_when(rng, now)
    return TransactionResponse(
        id=str(uuid4()),
        customer_id=customer_id,
        amount=round(amt, 2),
        currency="NGN",
        transaction_type=tx_type,
        narrative=narrative,
        counterparty_id=cp_id,
        counterparty_name=cp_name,
        status="posted",
        created_at=when,
        metadata=meta,
    )


ROUTINE_FLAVOURS: tuple[str, ...] = (
    "nip_in",
    "nip_out",
    "nibss_collect",
    "card_settlement",
    "card_spend",
    "pos_settlement",
    "pos_spend",
    "ussd_in",
    "ussd_out",
    "atm",
)


async def run_statement_bulk_seed(
    emit: EmitFn,
    *,
    now: datetime | None = None,
    seed: int = 77,
    routine_count: int = 1_550,
    suspicious_outflows_per_scenario: int = 20,
) -> Dict[str, Any]:
    """
    Emit ``routine_count`` routine in/out transactions across all demo customers, plus
    ``suspicious_outflows_per_scenario`` dissipation-style outflows for each DEMO-SC-* customer.
    """
    now = now or datetime.utcnow()
    rng = random.Random(seed)
    created_ids: List[str] = []

    async def _e(txn: TransactionResponse) -> None:
        created_ids.append(txn.id)
        await emit(txn)

    for _ in range(routine_count):
        customer_id = rng.choice(ALL_DEMO_CUSTOMER_IDS)
        flavour = rng.choice(ROUTINE_FLAVOURS)
        txn = _build_routine_txn(rng, now, customer_id, flavour=flavour)
        await _e(txn)

    structuring_amounts = (
        95_000,
        99_500,
        490_000,
        995_000,
        1_450_000,
        2_980_000,
        4_850_000,
    )

    async def emit_suspicious(sc_customer: str) -> None:
        base = now - timedelta(days=rng.randint(5, 90))
        for i in range(suspicious_outflows_per_scenario):
            pattern = rng.choice(
                (
                    "structuring_split",
                    "internal_sweep",
                    "external_drain",
                    "same_day_layer",
                    "bulk_wire_out",
                )
            )
            amt = float(rng.choice(structuring_amounts) + rng.randint(-2_500, 8_800))
            amt = max(8_000, round(amt, 2))
            ts = base + timedelta(hours=i * rng.randint(2, 18) + rng.randint(0, 120))

            if pattern == "internal_sweep":
                tx_type = "transfer_out"
                narrative = (
                    f"Internal book transfer — {rng.choice(INTERNAL_BRANCH_LABELS)} "
                    f"(related-account sweep ref INT-{rng.randint(6600000, 6699999)})"
                )
                meta = _md(
                    channel="internal_transfer",
                    payment_rail="book_transfer",
                    suspicious_dissipation=True,
                    demo_scenario_outflow=True,
                    structuring_indicator="below_threshold_sequence",
                    demo_statement_seed=True,
                )
                cp_id = f"INT-REL-{rng.randint(1000, 9999)}"
                cp_name = "Legacy Bank — internal ops"
            elif pattern == "external_drain":
                tx_type = "transfer_out"
                narrative = (
                    f"NIP out to third-party bank — dissipation leg {i + 1}/{suspicious_outflows_per_scenario} "
                    f"beneficiary {rng.choice(EXTERNAL_BANKS)}"
                )
                meta = _md(
                    channel="nibss",
                    payment_rail="NIP",
                    suspicious_dissipation=True,
                    demo_scenario_outflow=True,
                    integration_leg="post_inflow_exit",
                    demo_statement_seed=True,
                )
                cp_id = f"EXT-DRAIN-{rng.randint(20000, 99999)}"
                cp_name = rng.choice(EXTERNAL_BANKS) + " — beneficiary"
            elif pattern == "same_day_layer":
                tx_type = "transfer_out"
                narrative = (
                    f"SWIFT / correspondent outward — same-day routing "
                    f"(REF STRATO-{rng.randint(7700000, 7799999)})"
                )
                meta = _md(
                    channel="swift_correspondent",
                    payment_rail="SWIFT",
                    suspicious_dissipation=True,
                    demo_scenario_outflow=True,
                    layering_hint=True,
                    demo_statement_seed=True,
                )
                cp_id = f"SWF-CORR-{rng.randint(100000, 999999)}"
                cp_name = "Correspondent beneficiary"
            elif pattern == "bulk_wire_out":
                tx_type = "transfer_out"
                narrative = (
                    f"Bulk customer payout batch debit — suspected consolidation before external move "
                    f"(batch PB-{rng.randint(880000, 889999)})"
                )
                meta = _md(
                    channel="nibss",
                    payment_rail="bulk_DEBIT",
                    suspicious_dissipation=True,
                    demo_scenario_outflow=True,
                    rapid_outflow_cluster=True,
                    demo_statement_seed=True,
                )
                cp_id = f"BULK-PB-{rng.randint(100000, 999999)}"
                cp_name = "Batch settlement pool"
            else:
                tx_type = "transfer_out"
                narrative = (
                    f"Sequential NIP out — amount adjacent to reporting threshold segment {i + 1} "
                    f"to {rng.choice(['beneficiary A', 'nominee account', 'trade shell'])}"
                )
                meta = _md(
                    channel="nibss",
                    payment_rail="NIP",
                    suspicious_dissipation=True,
                    demo_scenario_outflow=True,
                    structuring_pattern="threshold_adjacent",
                    demo_statement_seed=True,
                )
                cp_id = f"SEQ-STR-{rng.randint(30000, 99999)}"
                cp_name = rng.choice(EXTERNAL_BANKS)

            txn = TransactionResponse(
                id=str(uuid4()),
                customer_id=sc_customer,
                amount=amt,
                currency="NGN",
                transaction_type=tx_type,
                narrative=narrative,
                counterparty_id=cp_id,
                counterparty_name=cp_name,
                status="posted",
                created_at=ts,
                metadata=meta,
            )
            await _e(txn)

    for sc in SCENARIO_CUSTOMER_IDS:
        await emit_suspicious(sc)

    return {
        "routine_transactions": routine_count,
        "suspicious_outflow_transactions": len(SCENARIO_CUSTOMER_IDS) * suspicious_outflows_per_scenario,
        "scenario_customers": list(SCENARIO_CUSTOMER_IDS),
        "total_customers_in_pool": len(ALL_DEMO_CUSTOMER_IDS),
        "transaction_ids": created_ids,
        "seed": seed,
    }
