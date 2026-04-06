"""
Generate multi-year synthetic transaction histories for AML pattern learning and scenario testing.

For every simulated customer profile: dense **baseline** activity (salary where applicable, transfers **in and out**,
POS, routine cash deposit and **cash withdrawal**). Injects typology scenarios on staggered years, then adds
**integration / outflow legs** after those events (wire exit, transfers out, cash withdrawal) so narratives show
money moving on after suspicious spikes — closer to filing-ready flows than one-sided credits only.
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

    def _narrative_for_routine(typ: str) -> str:
        if typ == "transfer_in":
            return "NIP transfer in — family support / business receipt"
        if typ == "transfer_out":
            return "NIP transfer out — supplier payment / rent / school fees"
        if typ == "pos_settlement":
            return "POS settlement credit — retail clearing"
        return "Routine transfer"

    total_days = years * 365
    # --- Baseline: normal inflows/outflows for every simulated customer across the timeline ---
    for d in range(0, total_days, 3):  # every 3 days grid
        day = start + timedelta(days=d)
        if len(txns) >= max_transactions:
            break
        for p in profiles:
            if len(txns) >= max_transactions:
                break
            # Most days have some activity per customer (still sparse for realism)
            if rng.random() > 0.26:
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
            elif rng.random() < 0.50:
                lo, hi = p.small_transfer_range
                amt = rng.uniform(lo, hi)
                typ = rng.choice(["transfer_in", "transfer_out", "transfer_in", "pos_settlement", "transfer_out"])
                txns.append(
                    _tx(
                        p.customer_id,
                        when,
                        amt,
                        typ,
                        narrative=_narrative_for_routine(typ),
                        metadata={"pattern": "routine", "profile": p.label},
                    )
                )
            elif rng.random() < 0.14:
                cap = min(p.max_normal_cash, 120_000)
                amt = rng.uniform(5_000, cap)
                txns.append(
                    _tx(
                        p.customer_id,
                        when,
                        amt,
                        "cash_deposit",
                        narrative="Cash lodgment — branch teller",
                        metadata={"pattern": "routine_cash", "profile": p.label},
                    )
                )
            elif rng.random() < 0.55:
                cap_w = min(p.max_normal_cash, 150_000)
                amt = rng.uniform(4_000, cap_w)
                txns.append(
                    _tx(
                        p.customer_id,
                        when,
                        amt,
                        "cash_withdrawal",
                        narrative="Cash withdrawal — ATM / branch (working capital)",
                        metadata={"pattern": "routine_cash_out", "profile": p.label},
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
                    metadata={"pattern": "smurfing", "cluster_id": f"smurf-{y}", "leg": "in"},
                ),
            )
        t_last_smurf = t0 + timedelta(minutes=5 * 17)
        if len(txns) < max_transactions:
            add_scenario(
                "SMURFING_INTEGRATION_OUT",
                _tx(
                    "DEMO-STUDENT-UNILAG",
                    t_last_smurf + timedelta(days=1, hours=4),
                    4_850_000,
                    "transfer_out",
                    narrative="Outward NIP — consolidated sweep to second bank account (integration leg)",
                    metadata={"pattern": "smurfing", "leg": "integration_out", "cluster_id": f"smurf-{y}"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "SMURFING_INTEGRATION_OUT",
                _tx(
                    "DEMO-STUDENT-UNILAG",
                    t_last_smurf + timedelta(days=3, hours=2),
                    3_100_000,
                    "wire",
                    narrative="Outward SWIFT — tuition / overseas fees (exit of pooled inflows)",
                    metadata={"pattern": "smurfing", "leg": "wire_exit", "cluster_id": f"smurf-{y}"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "SMURFING_INTEGRATION_OUT",
                _tx(
                    "DEMO-STUDENT-UNILAG",
                    t_last_smurf + timedelta(days=9),
                    920_000,
                    "cash_withdrawal",
                    narrative="Cash withdrawal — living expenses after large credit run",
                    metadata={"pattern": "smurfing", "leg": "cash_exit", "cluster_id": f"smurf-{y}"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "SMURFING_INTEGRATION_OUT",
                _tx(
                    "DEMO-STUDENT-UNILAG",
                    t_last_smurf + timedelta(days=24),
                    38_000,
                    "transfer_in",
                    narrative="Minor inbound — family top-up (routine after event)",
                    metadata={"pattern": "routine", "leg": "post_cluster_in", "cluster_id": f"smurf-{y}"},
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
        t_layer = t0 + timedelta(minutes=48)
        if len(txns) < max_transactions:
            add_scenario(
                "LAYERING_PASS_THROUGH",
                _tx(
                    "DEMO-TRADER-ABA",
                    t_layer + timedelta(days=2, hours=6),
                    2_050_000,
                    "transfer_out",
                    narrative="Supplier payment — wholesale fabric purchase (further distribution of inbound leg)",
                    metadata={"pattern": "layering", "leg": "integration_out"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "LAYERING_PASS_THROUGH",
                _tx(
                    "DEMO-TRADER-ABA",
                    t_layer + timedelta(days=5),
                    355_000,
                    "transfer_in",
                    narrative="Inbound refund — partial return from distributor (secondary inflow)",
                    metadata={"pattern": "layering", "leg": "round_in"},
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
        t_cash = t0 + timedelta(hours=2)
        if len(txns) < max_transactions:
            add_scenario(
                "CASH_PROFILE_FOLLOWUP_OUT",
                _tx(
                    "DEMO-STUDENT-UNILAG",
                    t_cash + timedelta(days=1, hours=5),
                    4_200_000,
                    "transfer_out",
                    narrative="Outward transfer — fees and disbursements to third-party agent account",
                    metadata={"pattern": "cash_anomaly", "leg": "outflow_after_deposit"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "CASH_PROFILE_FOLLOWUP_OUT",
                _tx(
                    "DEMO-STUDENT-UNILAG",
                    t_cash + timedelta(days=4),
                    1_100_000,
                    "cash_withdrawal",
                    narrative="Cash withdrawal — branch payout after large lodgments",
                    metadata={"pattern": "cash_anomaly", "leg": "cash_exit"},
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
        t_struct_end = t0 + timedelta(hours=18)
        staged_total = 990_000 * 10
        if len(txns) < max_transactions:
            add_scenario(
                "STRUCTURING_INTEGRATION_OUT",
                _tx(
                    "DEMO-WORKER-LAGOS",
                    t_struct_end + timedelta(days=2),
                    staged_total * 0.38,
                    "transfer_out",
                    narrative="Outward NIP — consolidated movement after structured cash credits",
                    metadata={"pattern": "structuring", "leg": "integration_out_1"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "STRUCTURING_INTEGRATION_OUT",
                _tx(
                    "DEMO-WORKER-LAGOS",
                    t_struct_end + timedelta(days=5),
                    staged_total * 0.28,
                    "transfer_out",
                    narrative="Second outward leg — property agent / cooperative account",
                    metadata={"pattern": "structuring", "leg": "integration_out_2"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "STRUCTURING_INTEGRATION_OUT",
                _tx(
                    "DEMO-WORKER-LAGOS",
                    t_struct_end + timedelta(days=11),
                    420_000,
                    "cash_withdrawal",
                    narrative="Cash withdrawal — residual balance after electronic sweeps",
                    metadata={"pattern": "structuring", "leg": "cash_exit"},
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
        t_vel_end = t0 + timedelta(minutes=2 * 39)
        if len(txns) < max_transactions:
            add_scenario(
                "VELOCITY_SETTLEMENT_OUT",
                _tx(
                    "DEMO-MERCHANT-OGBA",
                    t_vel_end + timedelta(hours=6),
                    285_000,
                    "transfer_out",
                    narrative="Supplier settlement — inventory purchase after POS spike",
                    metadata={"pattern": "velocity", "leg": "outflow_supplier"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "VELOCITY_SETTLEMENT_OUT",
                _tx(
                    "DEMO-MERCHANT-OGBA",
                    t_vel_end + timedelta(days=1),
                    142_000,
                    "transfer_out",
                    narrative="Wallet sweep — Opay / mobile money redistribution",
                    metadata={"pattern": "velocity", "leg": "outflow_wallet"},
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
                metadata={"pattern": "wire_spike", "leg": "in"},
            ),
        )
        if len(txns) < max_transactions:
            add_scenario(
                "WIRE_SPIKE_OUT",
                _tx(
                    "DEMO-WORKER-LAGOS",
                    t0 + timedelta(days=2),
                    11_500_000,
                    "transfer_out",
                    narrative="Outward transfer — property purchase via solicitor trust account",
                    metadata={"pattern": "wire_spike", "leg": "property_exit"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "WIRE_SPIKE_OUT",
                _tx(
                    "DEMO-WORKER-LAGOS",
                    t0 + timedelta(days=5),
                    5_200_000,
                    "transfer_out",
                    narrative="FX conversion outward — BDC / parallel market settlement",
                    metadata={"pattern": "wire_spike", "leg": "fx_exit"},
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
        t_rt = t0 + timedelta(days=3)
        if len(txns) < max_transactions:
            add_scenario(
                "ROUND_TRIP_FOLLOWOUT",
                _tx(
                    "DEMO-IMPORTER-APAPA",
                    t_rt + timedelta(days=4),
                    amt * 0.72,
                    "transfer_out",
                    narrative="Forward outward — shipping line / customs charges (use of returned funds)",
                    metadata={"pattern": "round_trip", "leg": "post_return_out"},
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
                metadata={"pattern": "channel_shift", "counterparty_risk": "high", "leg": "in"},
            ),
        )
        if len(txns) < max_transactions:
            add_scenario(
                "CHANNEL_ANOMALY_OUT",
                _tx(
                    "DEMO-HNWI-VI",
                    t0 + timedelta(days=3),
                    14_000_000,
                    "transfer_out",
                    narrative="Subsidiary capital injection — group treasury redistribution",
                    metadata={"pattern": "channel_shift", "leg": "treasury_out"},
                ),
            )
        if len(txns) < max_transactions:
            add_scenario(
                "CHANNEL_ANOMALY_OUT",
                _tx(
                    "DEMO-HNWI-VI",
                    t0 + timedelta(days=9),
                    9_200_000,
                    "transfer_out",
                    narrative="Real estate JV contribution — escrow outward leg",
                    metadata={"pattern": "channel_shift", "leg": "jv_out"},
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
