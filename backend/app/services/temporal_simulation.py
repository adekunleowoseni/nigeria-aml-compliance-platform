"""
Generate multi-year synthetic transaction histories for AML pattern learning and scenario testing.

Produces normal recurring behaviour per customer profile, then injects known suspicious patterns
across the timeline so Isolation Forest + rules can surface outliers vs 10-year baselines.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from app.models.transaction import TransactionResponse


@dataclass(frozen=True)
class CustomerSimProfile:
    customer_id: str
    label: str
    # Typical monthly inflow range (NGN)
    salary_range: Tuple[float, float] | None
    small_transfer_range: Tuple[float, float]
    max_normal_cash: float


# Six archetypes spanning retail, student, trader, HNWI, merchant, importer
DEFAULT_PROFILES: Tuple[CustomerSimProfile, ...] = (
    CustomerSimProfile(
        "DEMO-WORKER-LAGOS",
        "civil_servant_ippis_lagos",
        (220_000, 320_000),
        (2_000, 45_000),
        150_000,
    ),
    CustomerSimProfile(
        "DEMO-STUDENT-UNILAG",
        "student_unilag_low_income",
        None,
        (3_000, 35_000),
        80_000,
    ),
    CustomerSimProfile(
        "DEMO-TRADER-ABA",
        "sme_fabric_trader_aba",
        (80_000, 180_000),
        (15_000, 400_000),
        500_000,
    ),
    CustomerSimProfile(
        "DEMO-HNWI-VI",
        "business_owner_victoria_island",
        (2_000_000, 5_000_000),
        (100_000, 2_000_000),
        5_000_000,
    ),
    CustomerSimProfile(
        "DEMO-MERCHANT-OGBA",
        "retail_phones_ogba",
        None,
        (500, 25_000),
        300_000,
    ),
    CustomerSimProfile(
        "DEMO-IMPORTER-APAPA",
        "clearing_forwarding_apapa",
        (400_000, 900_000),
        (50_000, 1_200_000),
        800_000,
    ),
)


def _tx(
    customer_id: str,
    when: datetime,
    amount: float,
    tx_type: str,
    *,
    narrative: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> TransactionResponse:
    md = dict(metadata or {})
    md.setdefault("simulated", True)
    return TransactionResponse(
        id=str(uuid4()),
        customer_id=customer_id,
        amount=round(amount, 2),
        currency="NGN",
        transaction_type=tx_type,
        status="posted",
        created_at=when,
        narrative=narrative,
        metadata=md,
    )


def generate_temporal_dataset(
    *,
    years: int = 10,
    seed: int = 42,
    profiles: Tuple[CustomerSimProfile, ...] = DEFAULT_PROFILES,
    max_transactions: int = 120_000,
) -> Tuple[List[TransactionResponse], Dict[str, Any]]:
    """
    Build ~10 years of monthly + sporadic normal activity per customer, then inject AML scenarios.

    Returns (sorted_transactions, summary_stats).
    """
    rng = random.Random(seed)
    now = datetime.utcnow()
    start = now - timedelta(days=365 * years)
    txns: List[TransactionResponse] = []
    scenario_counts: Dict[str, int] = {}

    def add_scenario(code: str, t: TransactionResponse) -> None:
        t.metadata = {**(t.metadata or {}), "simulation_scenario": code}
        txns.append(t)
        scenario_counts[code] = scenario_counts.get(code, 0) + 1

    total_days = years * 365
    # --- Baseline: spread normal activity across the timeline ---
    for d in range(0, total_days, 3):  # every 3 days grid
        day = start + timedelta(days=d)
        if len(txns) >= max_transactions:
            break
        for p in profiles:
            if len(txns) >= max_transactions:
                break
            # Skip some days randomly (not every customer transacts daily)
            if rng.random() > 0.35:
                continue
            hour = rng.randint(7, 21)
            minute = rng.randint(0, 59)
            when = day.replace(hour=hour, minute=minute, second=rng.randint(0, 59), microsecond=0)

            if p.salary_range and day.day <= 3 and rng.random() < 0.33:
                # salary cluster early month
                amt = rng.uniform(*p.salary_range)
                txns.append(
                    _tx(
                        p.customer_id,
                        when,
                        amt,
                        "salary",
                        narrative="IPPS salary credit — Office of the Accountant-General (October payroll)",
                        metadata={"pattern": "recurring_salary", "profile": p.label},
                    )
                )
            elif rng.random() < 0.55:
                lo, hi = p.small_transfer_range
                amt = rng.uniform(lo, hi)
                typ = rng.choice(["transfer_in", "transfer_out", "pos_settlement", "transfer_in"])
                txns.append(
                    _tx(
                        p.customer_id,
                        when,
                        amt,
                        typ,
                        narrative="NIP transfer in — family support / rent payment",
                        metadata={"pattern": "routine", "profile": p.label},
                    )
                )
            elif rng.random() < 0.12:
                cap = min(p.max_normal_cash, 120_000)
                amt = rng.uniform(5_000, cap)
                txns.append(
                    _tx(
                        p.customer_id,
                        when,
                        amt,
                        "cash_deposit",
                        narrative="Cash lodgment — branch teller Victoria Island",
                        metadata={"pattern": "routine_cash", "profile": p.label},
                    )
                )

    # --- Injected scenarios (spread across years) ---
    def offset_days(y: float, m: int, day: int) -> datetime:
        """Approximate calendar offset from start (y = year index 0..years-1)."""
        base = start + timedelta(days=int(365 * y) + 30 * m + day)
        h = rng.randint(8, 20)
        return base.replace(hour=h, minute=rng.randint(0, 59), second=0, microsecond=0)

    # 1) Smurfing / fan-in (student)
    for y in range(0, years, max(1, years // 4)):
        t0 = offset_days(y + 0.2, 2, 5)
        for i in range(18):
            add_scenario(
                "SMURFING_FAN_IN",
                _tx(
                    "DEMO-STUDENT-UNILAG",
                    t0 + timedelta(minutes=5 * i),
                    280_000 + i * 3_000,
                    "transfer_in",
                    narrative="UBA inward NIP — ref: family remittance batch (below typical threshold cluster)",
                    metadata={"pattern": "smurfing", "cluster_id": f"smurf-{y}"},
                ),
            )

    # 2) Layering (trader)
    for y in range(0, years, max(1, years // 3)):
        t0 = offset_days(y + 0.5, 6, 12)
        add_scenario(
            "LAYERING_PASS_THROUGH",
            _tx(
                "DEMO-TRADER-ABA",
                t0,
                12_000_000,
                "transfer_in",
                narrative="GTBank inward transfer — Chisco Transport Ltd settlement",
                metadata={"pattern": "layering", "leg": "in"},
            ),
        )
        add_scenario(
            "LAYERING_PASS_THROUGH",
            _tx(
                "DEMO-TRADER-ABA",
                t0 + timedelta(minutes=25),
                11_500_000,
                "transfer_out",
                narrative="Outward transfer — Access Bank / Kano beneficiary",
                metadata={"pattern": "layering", "leg": "out"},
            ),
        )
        add_scenario(
            "LAYERING_PASS_THROUGH",
            _tx(
                "DEMO-TRADER-ABA",
                t0 + timedelta(minutes=48),
                400_000,
                "transfer_out",
                narrative="Outward transfer — Opay wallet sweep",
                metadata={"pattern": "layering", "leg": "out"},
            ),
        )

    # 3) Cash vs profile (student)
    for y in range(0, years, max(1, years // 2)):
        t0 = offset_days(y + 0.15, 4, 20)
        add_scenario(
            "CASH_PROFILE_MISMATCH",
            _tx(
                "DEMO-STUDENT-UNILAG",
                t0,
                3_200_000,
                "cash_deposit",
                narrative="Cash deposit ₦3.2M — source declared as uncle gift (UNILAG student account)",
                metadata={"pattern": "cash_anomaly"},
            ),
        )
        add_scenario(
            "CASH_PROFILE_MISMATCH",
            _tx(
                "DEMO-STUDENT-UNILAG",
                t0 + timedelta(hours=2),
                2_900_000,
                "cash_deposit",
                narrative="Second cash lodgment same day — structuring review flag",
                metadata={"pattern": "cash_anomaly"},
            ),
        )

    # 4) Structuring (worker) — amounts just under threshold
    for y in range(0, years, max(1, years // 5)):
        t0 = offset_days(y + 0.3, 8, 1)
        for i in range(10):
            add_scenario(
                "STRUCTURING",
                _tx(
                    "DEMO-WORKER-LAGOS",
                    t0 + timedelta(hours=i * 2),
                    990_000,
                    "cash_deposit",
                    narrative="Cash deposit — amount just below internal monitoring threshold (repeat sequence)",
                    metadata={"pattern": "structuring", "sequence": i},
                ),
            )

    # 5) Velocity burst (merchant)
    for y in range(0, years, max(1, years // 4)):
        t0 = offset_days(y + 0.7, 1, 15)
        for i in range(40):
            add_scenario(
                "VELOCITY_BURST",
                _tx(
                    "DEMO-MERCHANT-OGBA",
                    t0 + timedelta(minutes=2 * i),
                    rng.uniform(8_000, 22_000),
                    "pos_settlement",
                    narrative="POS settlement batch — Palmpay aggregator (velocity spike vs history)",
                    metadata={"pattern": "velocity", "burst_year": y},
                ),
            )

    # 6) Sudden wire spike for low-wire profile (worker)
    for y in range(0, years, max(1, years // 3)):
        t0 = offset_days(y + 0.4, 11, 7)
        add_scenario(
            "WIRE_SPIKE",
            _tx(
                "DEMO-WORKER-LAGOS",
                t0,
                18_000_000,
                "wire",
                narrative="SWIFT inflow USD equivalent — sender Dubai commodity broker (inconsistent with IPPIS profile)",
                metadata={"pattern": "wire_spike"},
            ),
        )

    # 7) Round-tripping (importer)
    for y in range(0, years, max(1, years // 4)):
        t0 = offset_days(y + 0.25, 5, 18)
        amt = 4_500_000
        add_scenario(
            "ROUND_TRIP",
            _tx(
                "DEMO-IMPORTER-APAPA",
                t0,
                amt,
                "transfer_out",
                narrative="Outward transfer — Maersk Nigeria Ltd customs duty refund (suspected round-trip leg A)",
                metadata={"pattern": "round_trip", "leg": "out"},
            ),
        )
        add_scenario(
            "ROUND_TRIP",
            _tx(
                "DEMO-IMPORTER-APAPA",
                t0 + timedelta(days=3),
                amt * 0.98,
                "transfer_in",
                narrative="Inward transfer — same reference family as prior outbound (round-trip leg B)",
                metadata={"pattern": "round_trip", "leg": "in"},
            ),
        )

    # 8) HNWI sudden crypto-like narrative (metadata only) + atypical type
    for y in range(0, years, max(1, years // 5)):
        t0 = offset_days(y + 0.6, 9, 3)
        add_scenario(
            "CHANNEL_ANOMALY",
            _tx(
                "DEMO-HNWI-VI",
                t0,
                25_000_000,
                "wire",
                narrative="FCMB SWIFT — Lloyds London ref invoice INV-8842 (size vs 10y cadence)",
                metadata={"pattern": "channel_shift", "counterparty_risk": "high"},
            ),
        )

    # Sort chronologically for causal baseline when scoring
    txns.sort(key=lambda t: (t.created_at, t.id))

    summary = {
        "total_generated": len(txns),
        "year_span": years,
        "customers": len(profiles),
        "scenario_counts": scenario_counts,
        "seed": seed,
        "approx_start": start.isoformat(),
        "approx_end": now.isoformat(),
    }
    return txns, summary
