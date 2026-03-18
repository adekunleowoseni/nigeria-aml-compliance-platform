from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.core.security import get_current_user

router = APIRouter(prefix="/federated")


@router.get("/status")
async def status(user: Dict[str, Any] = Depends(get_current_user)):
    return {"enabled": False}

