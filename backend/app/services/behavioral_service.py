from __future__ import annotations

from typing import Any, Dict


class BehavioralService:
    async def score(self, transaction: Dict[str, Any]) -> float:
        # Placeholder behavioral heuristics
        amt = float(transaction.get("amount", 0))
        return min(1.0, amt / 50_000_000.0)

