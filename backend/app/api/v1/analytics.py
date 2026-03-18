from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user

router = APIRouter(prefix="/analytics")


@router.get("/dashboard")
async def dashboard_metrics(user: Dict[str, Any] = Depends(get_current_user)):
    # Placeholder metrics until DB integration
    return {
        "total_transactions": 0,
        "total_alerts": 0,
        "high_risk_count": 0,
        "pending_strs": 0,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/risk-distribution")
async def risk_distribution(bucket_count: int = Query(5, ge=3, le=20), user: Dict[str, Any] = Depends(get_current_user)):
    step = 1.0 / bucket_count
    buckets = []
    for i in range(bucket_count):
        buckets.append(
            {
                "min": round(i * step, 3),
                "max": round((i + 1) * step, 3),
                "count": 0,
                "label": f"{int(i*step*100)}-{int((i+1)*step*100)}%",
            }
        )
    return {"buckets": buckets, "bucket_count": bucket_count}


@router.get("/trends")
async def trends(metric: str = "alerts", granularity: str = "day", user: Dict[str, Any] = Depends(get_current_user)):
    return {"series": [], "metric": metric, "granularity": granularity}

