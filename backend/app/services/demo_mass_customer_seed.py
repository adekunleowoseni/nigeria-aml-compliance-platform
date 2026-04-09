from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Sequence
from uuid import uuid4

from app.models.transaction import TransactionResponse
from app.services.customer_kyc_db import upsert_customer_kyc_explicit

EmitFn = Callable[[TransactionResponse], Awaitable[None]]

FIRST_NAMES = (
    "Amina",
    "Bola",
    "Chinedu",
    "Ngozi",
    "Ifeanyi",
    "Zainab",
    "Tosin",
    "Maryam",
    "Uche",
    "Blessing",
    "Femi",
    "Sade",
    "Musa",
    "Kelechi",
    "Eniola",
    "Temitope",
    "Hauwa",
    "Oluwaseun",
    "David",
    "Adaobi",
)

LAST_NAMES = (
    "Adeyemi",
    "Okafor",
    "Bello",
    "Ibrahim",
    "Nwosu",
    "Ogunleye",
    "Umeh",
    "Balogun",
    "Olatunji",
    "Eze",
    "Ahmed",
    "Abubakar",
    "Onyeka",
    "Ogunbiyi",
    "Afolabi",
    "Nnamdi",
    "Bakare",
    "Lawal",
    "Suleiman",
    "Okechukwu",
)

OCCUPATIONS = (
    "Civil Servant",
    "Student",
    "SME Trader",
    "Business Owner",
    "Merchant",
    "Logistics / Importer",
    "Engineer",
    "Medical Practitioner",
    "Teacher",
    "Consultant",
)

SUSPICIOUS_SCENARIOS = (
    "STRUCTURING_SPLIT_RUN",
    "LAYERING_RAPID_HOPS",
    "PASS_THROUGH_DISSIPATION",
    "CASH_TO_ELECTRONIC_CONVERSION",
    "HIGH_VELOCITY_FAN_OUT",
)

SUSPICIOUS_RULE_CODES = (
    "TYP-STRUCTURING",
    "TYP-RAPID-INFLOW-OUTFLOW",
    "TYP-FAN-OUT",
    "TYP-PROFILE-MISMATCH",
    "TYP-PATTERN-INCONSISTENT",
)

SUSPICIOUS_ANOMALIES = (
    "ANOM-IFOREST-CORE",
    "ANOM-BULK-REFIT",
    "ANOM-AMOUNT-SPIKE",
    "ANOM-TIME-WINDOW-COLLISION",
    "ANOM-THRESHOLD-ADJACENT",
)


def _rand_phone(rng: random.Random) -> str:
    return f"+234{rng.randint(7000000000, 9099999999)}"


def _rand_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _rand_address(rng: random.Random) -> str:
    return f"No. {rng.randint(2, 98)} {rng.choice(['Unity', 'Market', 'Airport', 'Marina', 'GRA'])} Road, Lagos"


def _rand_nin(rng: random.Random) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(11))


def _build_routine_txn(rng: random.Random, customer_id: str, now: datetime) -> TransactionResponse:
    flavour = rng.choice(("nip_in", "nip_out", "card", "pos", "ussd", "atm"))
    when = now - timedelta(days=rng.randint(1, 240), seconds=rng.randint(0, 86399))
    cp = f"CP-{rng.randint(100000, 999999)}"
    if flavour == "nip_in":
        return TransactionResponse(
            id=str(uuid4()),
            customer_id=customer_id,
            amount=float(rng.randint(5_000, 2_000_000)),
            currency="NGN",
            transaction_type="transfer_in",
            narrative=f"NIBSS/NIP inward credit ref NIP-{rng.randint(1000000, 9999999)}",
            counterparty_id=cp,
            counterparty_name="NIP sender",
            status="posted",
            created_at=when,
            metadata={"channel": "nibss", "payment_rail": "NIP", "demo_bulk_seed": True},
        )
    if flavour == "nip_out":
        return TransactionResponse(
            id=str(uuid4()),
            customer_id=customer_id,
            amount=float(rng.randint(3_500, 1_800_000)),
            currency="NGN",
            transaction_type="transfer_out",
            narrative=f"NIBSS/NIP outward transfer ref NIP-{rng.randint(1000000, 9999999)}",
            counterparty_id=cp,
            counterparty_name="NIP beneficiary",
            status="posted",
            created_at=when,
            metadata={"channel": "nibss", "payment_rail": "NIP", "demo_bulk_seed": True},
        )
    if flavour == "card":
        return TransactionResponse(
            id=str(uuid4()),
            customer_id=customer_id,
            amount=float(rng.randint(1_000, 450_000)),
            currency="NGN",
            transaction_type="transfer_out",
            narrative="Card payment purchase settlement",
            counterparty_id=cp,
            counterparty_name="Card merchant",
            status="posted",
            created_at=when,
            metadata={"channel": "card", "payment_rail": "card_spend", "demo_bulk_seed": True},
        )
    if flavour == "pos":
        return TransactionResponse(
            id=str(uuid4()),
            customer_id=customer_id,
            amount=float(rng.randint(2_000, 850_000)),
            currency="NGN",
            transaction_type="pos_settlement",
            narrative="POS settlement / agent banking movement",
            counterparty_id=cp,
            counterparty_name="POS aggregator",
            status="posted",
            created_at=when,
            metadata={"channel": "pos", "payment_rail": "agent_banking", "demo_bulk_seed": True},
        )
    if flavour == "ussd":
        return TransactionResponse(
            id=str(uuid4()),
            customer_id=customer_id,
            amount=float(rng.randint(1_000, 250_000)),
            currency="NGN",
            transaction_type=rng.choice(("transfer_in", "transfer_out")),
            narrative="USSD transfer movement",
            counterparty_id=cp,
            counterparty_name="USSD hub",
            status="posted",
            created_at=when,
            metadata={"channel": "ussd", "payment_rail": "USSD", "demo_bulk_seed": True},
        )
    return TransactionResponse(
        id=str(uuid4()),
        customer_id=customer_id,
        amount=float(rng.randint(5_000, 300_000)),
        currency="NGN",
        transaction_type="cash_withdrawal",
        narrative="ATM cash withdrawal",
        counterparty_id=cp,
        counterparty_name="ATM switch",
        status="posted",
        created_at=when,
        metadata={"channel": "atm", "payment_rail": "ATM", "demo_bulk_seed": True},
    )


def _build_suspicious_txn(
    rng: random.Random,
    customer_id: str,
    now: datetime,
    *,
    seq: int,
) -> TransactionResponse:
    direction = rng.choice(("transfer_in", "transfer_out"))
    scenario = SUSPICIOUS_SCENARIOS[seq % len(SUSPICIOUS_SCENARIOS)]
    rule_code = SUSPICIOUS_RULE_CODES[seq % len(SUSPICIOUS_RULE_CODES)]
    anomaly = SUSPICIOUS_ANOMALIES[seq % len(SUSPICIOUS_ANOMALIES)]
    risk = min(0.99, 0.70 + ((seq % 30) * 0.01))
    when = now - timedelta(days=rng.randint(1, 120), minutes=rng.randint(0, 1439))
    amount = float(rng.randint(480_000, 9_500_000))
    if "STRUCTURING" in scenario:
        amount = float(rng.randint(940_000, 999_000))
    return TransactionResponse(
        id=str(uuid4()),
        customer_id=customer_id,
        amount=amount,
        currency="NGN",
        transaction_type=direction,
        narrative=(
            f"Suspicious {direction.replace('_', ' ')} leg {seq + 1} — {scenario} / {rule_code} / {anomaly}"
        ),
        counterparty_id=f"SUSP-{rng.randint(10000, 99999)}",
        counterparty_name="High-risk beneficiary",
        status="posted",
        created_at=when,
        metadata={
            "channel": "nibss",
            "payment_rail": "NIP",
            "demo_bulk_seed": True,
            "simulation_scenario": scenario,
            "seed_rule_code": rule_code,
            "seed_anomaly_tag": anomaly,
            "demo_severity": round(risk, 2),
            "suspicious_seed": True,
        },
    )


async def run_mass_customer_seed(
    *,
    pg: Any,
    emit: EmitFn,
    now: datetime,
    customer_count: int,
    risky_customer_count: int,
    suspicious_per_risky_customer: int,
    seed: int,
) -> Dict[str, Any]:
    rng = random.Random(seed)
    customer_ids: List[str] = []
    txn_ids: List[str] = []

    for i in range(customer_count):
        cid = f"DEMO-RND-{i + 1:05d}"
        customer_ids.append(cid)
        name = _rand_name(rng)
        lob = rng.choice(OCCUPATIONS)
        if "student" in cid.lower() or rng.random() < 0.08:
            lob = "Student"
        opened = date(2017 + (i % 8), 1 + (i % 12), 1 + (i % 27))
        dob = date(1972 + (i % 28), 1 + ((i * 3) % 12), 1 + ((i * 7) % 27))
        await upsert_customer_kyc_explicit(
            pg,
            cid,
            customer_name=name,
            account_number=f"{rng.randint(10**9, 10**10 - 1)}",
            account_opened=opened,
            customer_address=_rand_address(rng),
            line_of_business=lob,
            phone_number=_rand_phone(rng),
            date_of_birth=dob,
            id_number=_rand_nin(rng),
        )
        # Routine mixed-channel history
        for _ in range(rng.randint(6, 14)):
            t = _build_routine_txn(rng, cid, now)
            txn_ids.append(t.id)
            await emit(t)

    risky_ids = customer_ids[: max(0, min(risky_customer_count, len(customer_ids)))]
    suspicious_created = 0
    for cid in risky_ids:
        for seq in range(suspicious_per_risky_customer):
            t = _build_suspicious_txn(rng, cid, now, seq=seq)
            txn_ids.append(t.id)
            suspicious_created += 1
            await emit(t)

    return {
        "seeded_customers": len(customer_ids),
        "customer_ids": customer_ids,
        "risky_customer_ids": risky_ids,
        "suspicious_transactions": suspicious_created,
        "total_transactions": len(txn_ids),
        "transaction_ids": txn_ids,
        "seed": seed,
    }
