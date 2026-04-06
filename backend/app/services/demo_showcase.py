"""
High-risk typology showcase seed (demo): twelve AML scenario tracks with large amounts
and target alert severity 80–96% via metadata.demo_severity.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List
from uuid import uuid4

from app.models.transaction import TransactionResponse

Enqueue = Callable[[TransactionResponse], Awaitable[None]]


def _md(**kwargs: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {"demo_skip_llm": True, "showcase_pack": "HIGH_RISK_12"}
    for k, v in kwargs.items():
        if v is not None:
            base[k] = v
    return base


async def seed_high_risk_showcase(
    enqueue: Enqueue,
    *,
    now: datetime | None = None,
    capture: List[TransactionResponse] | None = None,
) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    created: List[str] = []
    cases: List[str] = []

    async def q(
        *,
        customer_id: str,
        amount: float,
        tx_type: str,
        narrative: str,
        hours_ago: float = 0,
        days_ago: float = 0,
        counterparty_id: str | None = None,
        counterparty_name: str | None = None,
        metadata: Dict[str, Any] | None = None,
        case: str | None = None,
    ) -> None:
        ts = now - timedelta(days=int(days_ago), seconds=int(hours_ago * 3600))
        md = dict(_md(**(metadata or {})))
        if case:
            md["showcase_case"] = case
        txn = TransactionResponse(
            id=str(uuid4()),
            customer_id=customer_id,
            amount=amount,
            currency="NGN",
            transaction_type=tx_type,
            narrative=narrative,
            counterparty_id=counterparty_id,
            counterparty_name=counterparty_name,
            status="posted",
            created_at=ts,
            metadata=md,
        )
        if capture is not None:
            capture.append(txn)
        await enqueue(txn)
        created.append(txn.id)

    # --- 1. PEP typology ---
    cases.append("pep_typology")
    await q(
        customer_id="DEMO-SC-PEP",
        amount=320_000.0,
        tx_type="salary",
        narrative="IPPIS salary credit — baseline",
        days_ago=60,
        counterparty_id="NIP-FGN-IPPIS",
        counterparty_name="Office of the Accountant-General of the Federation",
        metadata=_md(profile="civil_servant_ippis", sender_bank="CBN / IPPIS"),
        case="pep_typology",
    )
    await q(
        customer_id="DEMO-SC-PEP",
        amount=88_500_000.0,
        tx_type="wire",
        narrative=(
            "Consultancy and logistics retainer — Honourable Senator liaison office; "
            "PEP-related entity payment ref LEG-PEP-2026-09 (source-of-wealth review required)"
        ),
        hours_ago=2,
        counterparty_id="CP-SENATE-LIAISON",
        counterparty_name="Senate Appropriations Liaison Office",
        metadata=_md(
            profile="civil_servant_ippis",
            sender_bank="First Bank of Nigeria",
            pep_flag=True,
            counterparty_type="company",
            demo_severity=0.91,
        ),
        case="pep_typology",
    )

    # --- 2. Mole / pass-through ---
    cases.append("mole_pass_through")
    await q(
        customer_id="DEMO-SC-MOLE",
        amount=85_000.0,
        tx_type="transfer_in",
        narrative="Petty cash top-up",
        days_ago=14,
        counterparty_id="CP-MOLE-SEED",
        counterparty_name="Retail Collections Ltd",
        metadata=_md(profile="individual_sme"),
        case="mole_pass_through",
    )
    await q(
        customer_id="DEMO-SC-MOLE",
        amount=78_000_000.0,
        tx_type="transfer_in",
        narrative="Bulk receipt — nominee settlement (opaque source) ref MOLE-IN-01",
        hours_ago=30,
        counterparty_id="CP-NOMINEE-SHELL",
        counterparty_name="Opaque Nominees Holdings Ltd",
        metadata=_md(profile="individual_sme", sender_bank="Stanbic IBTC"),
        case="mole_pass_through",
    )
    for i, (amt, cpid, cpname) in enumerate(
        [
            (26_000_000.0, "CP-MOLE-OUT-01", "FastMove Distributors Ltd"),
            (26_000_000.0, "CP-MOLE-OUT-02", "Kano General Merchants Ltd"),
            (26_000_000.0, "CP-MOLE-OUT-03", "Port Harcourt Clearing Nominees"),
        ],
        start=1,
    ):
        await q(
            customer_id="DEMO-SC-MOLE",
            amount=amt,
            tx_type="transfer_out",
            narrative=f"Pass-through settlement tranche {i} — same-day disbursement",
            hours_ago=28 - i * 0.5,
            counterparty_id=cpid,
            counterparty_name=cpname,
            metadata=_md(
                profile="individual_sme",
                sender_bank="Guaranty Trust Bank",
                demo_severity=0.93 if i == 3 else None,
            ),
            case="mole_pass_through",
        )

    # --- 3. Dedicated hub → multiple beneficiaries (same-bank corridor) ---
    cases.append("hub_fan_out_same_bank")
    await q(
        customer_id="DEMO-SC-HUB",
        amount=400_000.0,
        tx_type="transfer_in",
        narrative="Operating float",
        days_ago=20,
        counterparty_id="CP-HUB-SEED",
        counterparty_name="Internal Float",
        metadata=_md(profile="project_hub_account"),
        case="hub_fan_out_same_bank",
    )
    await q(
        customer_id="DEMO-SC-HUB",
        amount=142_000_000.0,
        tx_type="transfer_in",
        narrative="Credit from dedicated project escrow — Zamfara rural electrification phase IV",
        hours_ago=26,
        counterparty_id="ESCROW-DED-ZAM",
        counterparty_name="Zamfara State Project Escrow (Dedicated Account)",
        metadata=_md(profile="project_hub_account", sender_bank="Access Bank", counterparty_type="company"),
        case="hub_fan_out_same_bank",
    )
    split = 17_750_000.0
    for i in range(1, 9):
        await q(
            customer_id="DEMO-SC-HUB",
            amount=split,
            tx_type="transfer_out",
            narrative=f"Sub-contractor payment batch HUB-{i:02d} (same institution rails)",
            hours_ago=25 - i * 0.15,
            counterparty_id=f"CP-HUB-BEN-{i:02d}",
            counterparty_name=f"Beneficiary Account {i:02d} — Access Bank corridor",
            metadata=_md(
                profile="project_hub_account",
                sender_bank="Access Bank",
                demo_severity=0.92 if i == 8 else None,
            ),
            case="hub_fan_out_same_bank",
        )

    # --- 4. Identical narration → multiple accounts ---
    cases.append("identical_narration_multi_account")
    shared_narr = (
        "BATCH PAYMENT REF-8821990 AGRIC INPUTS SUPPLY KANO (IDENTICAL REF ALL BRANCHES) — DO NOT ALTER NARRATION"
    )
    for tag in ("A", "B", "C", "D"):
        cid = f"DEMO-SC-SPL-{tag}"
        await q(
            customer_id=cid,
            amount=250_000.0,
            tx_type="transfer_in",
            narrative="Family transfer — baseline",
            days_ago=25,
            counterparty_id="CP-SPL-BASE",
            counterparty_name="Family Transfer",
            metadata=_md(profile="individual_retail_account"),
            case="identical_narration_multi_account",
        )
        await q(
            customer_id=cid,
            amount=18_750_000.0,
            tx_type="transfer_in",
            narrative=shared_narr,
            hours_ago=4 + ord(tag) * 0.05,
            counterparty_id="CP-AGRO-MASTER",
            counterparty_name="Northern Agric Inputs Consolidated Ltd",
            metadata=_md(
                profile="individual_retail_account",
                sender_bank="United Bank for Africa",
                demo_severity=0.88 if tag == "D" else 0.86,
            ),
            case="identical_narration_multi_account",
        )

    # --- 5. Terror / proliferation + jurisdiction indicators (simulation only) ---
    cases.append("terror_financing_indicators")
    await q(
        customer_id="DEMO-SC-TERROR",
        amount=120_000.0,
        tx_type="transfer_in",
        narrative="Salary credit",
        days_ago=40,
        counterparty_id="CP-T-EMP",
        counterparty_name="Employer Ltd",
        metadata=_md(profile="logistics_staff"),
        case="terror_financing_indicators",
    )
    await q(
        customer_id="DEMO-SC-TERROR",
        amount=47_800_000.0,
        tx_type="wire",
        narrative=(
            "Wire — chemical precursor procurement; consignment references Damascus route "
            "(Syria) and explosive-grade material wording per supplier invoice SY-EXP-441"
        ),
        hours_ago=1.5,
        counterparty_id="CP-SHAM-SY",
        counterparty_name="Al-Sham Industrial Trading (Syria)",
        metadata=_md(
            profile="logistics_staff",
            sender_bank="Standard Chartered",
            counterparty_type="company",
            demo_severity=0.95,
        ),
        case="terror_financing_indicators",
    )

    # --- 6. Tax evasion / under-declared turnover ---
    cases.append("tax_evasion_indicators")
    await q(
        customer_id="DEMO-SC-TAX",
        amount=95_000.0,
        tx_type="transfer_in",
        narrative="Market sales — small daily",
        days_ago=30,
        counterparty_id="CP-TAX-SEED",
        counterparty_name="Walk-in buyer",
        metadata=_md(profile="tailor_yaba_market", expected_annual_turnover=350_000.0),
        case="tax_evasion_indicators",
    )
    await q(
        customer_id="DEMO-SC-TAX",
        amount=43_200_000.0,
        tx_type="cash_deposit",
        narrative=(
            "Cash lodgment — consolidated diary sales and informal contracts; "
            "no FIRS withholding ref on narration (undeclared turnover suspicion)"
        ),
        hours_ago=3,
        counterparty_id="CASH-TELLER-LAGOS",
        counterparty_name="Cash — Main Branch Lagos",
        metadata=_md(
            profile="tailor_yaba_market",
            expected_annual_turnover=350_000.0,
            pattern="informal_cash_business",
            demo_severity=0.87,
        ),
        case="tax_evasion_indicators",
    )

    # --- 7. Structured / split inflows ---
    cases.append("structured_transfers")
    for i in range(1, 7):
        await q(
            customer_id="DEMO-SC-STRUCT",
            amount=485_000.0 + i * 1_200.0,
            tx_type="transfer_in",
            narrative=f"NIP in — goods payment segment {i} (split settlement)",
            hours_ago=8 - i * 0.4,
            counterparty_id=f"CP-STR-{i:02d}",
            counterparty_name=f"Structured payer entity {i:02d}",
            metadata=_md(profile="student_unilag_low_income", sender_bank="Zenith Bank"),
            case="structured_transfers",
        )
    await q(
        customer_id="DEMO-SC-STRUCT",
        amount=3_200_000.0,
        tx_type="transfer_in",
        narrative="Consolidation credit after split segments — sweep to main wallet",
        hours_ago=1,
        counterparty_id="CP-STR-AGG",
        counterparty_name="Aggregation Nominee",
        metadata=_md(
            profile="student_unilag_low_income",
            sender_bank="Zenith Bank",
            demo_severity=0.85,
        ),
        case="structured_transfers",
    )

    # --- 8. Large in + large out (rapid movement) ---
    cases.append("in_out_rapid")
    await q(
        customer_id="DEMO-SC-IO",
        amount=210_000.0,
        tx_type="transfer_in",
        narrative="Baseline float",
        days_ago=10,
        counterparty_id="CP-IO-BASE",
        counterparty_name="Base credit",
        metadata=_md(profile="sme_fabric_trader"),
        case="in_out_rapid",
    )
    await q(
        customer_id="DEMO-SC-IO",
        amount=64_000_000.0,
        tx_type="transfer_in",
        narrative="Import LC settlement — textile container TIANJIN-4401",
        hours_ago=6,
        counterparty_id="CP-IO-IMPORT",
        counterparty_name="Tianjin Textile Export Ltd",
        metadata=_md(profile="sme_fabric_trader", sender_bank="Ecobank Nigeria"),
        case="in_out_rapid",
    )
    await q(
        customer_id="DEMO-SC-IO",
        amount=61_500_000.0,
        tx_type="transfer_out",
        narrative="Same-day outward — distributor settlement and wallet sweep",
        hours_ago=5.5,
        counterparty_id="CP-IO-OUT",
        counterparty_name="Multi-city Distributors Pool",
        metadata=_md(
            profile="sme_fabric_trader",
            sender_bank="Ecobank Nigeria",
            channel="wallet",
            demo_severity=0.90,
        ),
        case="in_out_rapid",
    )

    # --- 9. Cryptocurrency / VA references ---
    cases.append("cryptocurrency_remarks")
    await q(
        customer_id="DEMO-SC-CRYPTO",
        amount=410_000.0,
        tx_type="transfer_in",
        narrative="Regular shop sales",
        days_ago=18,
        counterparty_id="CP-CR-BASE",
        counterparty_name="Walk-in",
        metadata=_md(profile="individual_retail_account"),
        case="cryptocurrency_remarks",
    )
    await q(
        customer_id="DEMO-SC-CRYPTO",
        amount=29_500_000.0,
        tx_type="transfer_in",
        narrative=(
            "BTC / ETH off-ramp settlement via Binance P2P — USDT batch ref USDT-OTC-99102; "
            "wallet addr logged on ticket"
        ),
        hours_ago=2,
        counterparty_id="CP-P2P-OTC",
        counterparty_name="Lagos OTC Desk Merchant",
        metadata=_md(
            profile="individual_retail_account",
            sender_bank="Providus Bank",
            demo_severity=0.89,
        ),
        case="cryptocurrency_remarks",
    )

    # --- 10. Ransom / kidnapping wording (simulation) ---
    cases.append("ransom_kidnap_wording")
    await q(
        customer_id="DEMO-SC-RANSOM",
        amount=180_000.0,
        tx_type="transfer_in",
        narrative="Salary",
        days_ago=35,
        counterparty_id="CP-RAN-EMP",
        counterparty_name="Employer",
        metadata=_md(profile="individual_sme"),
        case="ransom_kidnap_wording",
    )
    await q(
        customer_id="DEMO-SC-RANSOM",
        amount=36_000_000.0,
        tx_type="wire",
        narrative=(
            "Kidnap ransom release payment tranche 2 — follow courier instructions; "
            "do not disclose to third parties (urgent)"
        ),
        hours_ago=0.5,
        counterparty_id="CP-RANSOM-NOM",
        counterparty_name="Unverified Nominee Receiver",
        metadata=_md(profile="individual_sme", sender_bank="FCMB", demo_severity=0.94),
        case="ransom_kidnap_wording",
    )

    # --- 11. Government / embezzlement-style flow ---
    cases.append("government_embezzlement_theme")
    await q(
        customer_id="DEMO-SC-EMBEZ",
        amount=280_000.0,
        tx_type="salary",
        narrative="MDA salary baseline",
        days_ago=50,
        counterparty_id="NIP-FGN-IPPIS",
        counterparty_name="Office of the Accountant-General of the Federation",
        metadata=_md(profile="civil_servant_ippis"),
        case="government_embezzlement_theme",
    )
    await q(
        customer_id="DEMO-SC-EMBEZ",
        amount=33_500_000.0,
        tx_type="transfer_out",
        narrative=(
            "Outward transfer — Federal Ministry of Agriculture logistics vote reimbursement; "
            "beneficiary private company (verify procurement records)"
        ),
        hours_ago=4,
        counterparty_id="CP-EMBEZ-NOM",
        counterparty_name="Agri Logistics Nominees Ltd",
        metadata=_md(
            profile="civil_servant_ippis",
            sender_bank="Zenith Bank",
            demo_severity=0.90,
        ),
        case="government_embezzlement_theme",
    )

    # --- 12. SAR-style composite (multiple red flags) ---
    cases.append("sar_composite_customer")
    await q(
        customer_id="DEMO-SC-SAR",
        amount=60_000.0,
        tx_type="transfer_in",
        narrative="Pocket money",
        days_ago=45,
        counterparty_id="CP-SAR-BASE",
        counterparty_name="Parent transfer",
        metadata=_md(profile="student_unilag_low_income", expected_annual_turnover=120_000.0),
        case="sar_composite_customer",
    )
    await q(
        customer_id="DEMO-SC-SAR",
        amount=16_800_000.0,
        tx_type="transfer_in",
        narrative=(
            "Corporate inflow — staff payroll bulk and USDT settlement note on cover letter "
            "(Chinedu Logistics Plc)"
        ),
        hours_ago=1,
        counterparty_id="CP-SAR-CORP",
        counterparty_name="Chinedu Logistics Plc",
        metadata=_md(
            profile="student_unilag_low_income",
            customer_segment="retail",
            account_class="individual",
            counterparty_type="company",
            sender_bank="Access Bank",
            expected_annual_turnover=120_000.0,
            demo_severity=0.93,
        ),
        case="sar_composite_customer",
    )

    return {
        "seeded_transactions": len(created),
        "transaction_ids": created,
        "showcase_cases": cases,
        "note": "Synthetic demo data for training and UI only — not real persons or events.",
    }
