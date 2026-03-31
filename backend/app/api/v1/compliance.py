from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.services.sanctions_screening import screen_name_opensanctions

router = APIRouter(prefix="/compliance")

# Reference only — not a substitute for official UN / OFAC / EU lists. UI table + analyst guidance.
FATF_STYLE_HIGH_RISK_JURISDICTIONS: List[Dict[str, str]] = [
    {"jurisdiction": "Afghanistan", "note": "High-risk / conflict (verify current FATF lists)."},
    {"jurisdiction": "Democratic People's Republic of Korea (DPRK)", "note": "Comprehensive sanctions — UN / multilateral."},
    {"jurisdiction": "Iran", "note": "Sanctions and sectoral restrictions — verify OFAC / EU."},
    {"jurisdiction": "Myanmar", "note": "Elevated ML/TF risk — monitor FATF statements."},
    {"jurisdiction": "Syria", "note": "Comprehensive sanctions regimes."},
    {"jurisdiction": "Yemen", "note": "Conflict and TF risk."},
    {"jurisdiction": "Haiti", "note": "FATF grey/black list — verify current public statements."},
    {"jurisdiction": "South Sudan", "note": "Corruption and conflict financing risk."},
    {"jurisdiction": "Burkina Faso", "note": "Jurisdictions under increased monitoring — verify FATF updates."},
    {"jurisdiction": "Cayman Islands", "note": "Historically cited for strategic deficiencies — verify FATF Jurisdictions under increased monitoring."},
    {"jurisdiction": "Panama", "note": "Verify current FATF / regional assessments."},
    {"jurisdiction": "Uganda", "note": "Example entry — replace with your institution’s approved list."},
]


@router.get("/sanctions/reference-jurisdictions")
async def reference_jurisdictions(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Static reference table for UI; official lists must be subscribed from regulators / data vendors."""
    return {
        "source": "internal_reference_only",
        "disclaimer": "Not an official sanctions list. Use UN, OFAC, EU, UK HMT, and NFIU guidance for filing.",
        "jurisdictions": FATF_STYLE_HIGH_RISK_JURISDICTIONS,
    }


@router.get("/sanctions/screen")
async def screen_sanctions(
    name: str = Query(..., min_length=2, description="Person or entity name to screen"),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Online screening via OpenSanctions API (no local sanctions database required).
    """
    return await screen_name_opensanctions(name)
