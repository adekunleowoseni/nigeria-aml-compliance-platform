from __future__ import annotations

from typing import Any, Dict

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.security import create_access_token, get_current_user

router = APIRouter(prefix="/auth")


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# Default admin (change password via API after first login in production)
ADMIN_EMAIL = "admin@admin.com"
ADMIN_DEFAULT_PASSWORD = "12345678"

# In-memory users (demo platform). Password is bcrypt-hashed.
_users: Dict[str, Dict[str, Any]] = {
    ADMIN_EMAIL.lower(): {
        "email": ADMIN_EMAIL,
        "password_hash": _hash_password(ADMIN_DEFAULT_PASSWORD),
        "role": "admin",
        "display_name": "Administrator",
    },
}


class LoginBody(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginBody) -> LoginResponse:
    key = body.email.strip().lower()
    user = _users.get(key)
    if not user or not _verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token(
        user["email"],
        extra={"role": user["role"], "email": user["email"]},
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user={
            "email": user["email"],
            "role": user["role"],
            "display_name": user["display_name"],
        },
    )


@router.get("/me")
async def me(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "sub": user.get("sub"),
        "email": user.get("email") or user.get("sub"),
        "role": user.get("role"),
    }


@router.post("/change-password")
async def change_password(
    body: ChangePasswordBody,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, str]:
    email = (user.get("email") or user.get("sub") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session")
    rec = _users.get(email)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not _verify_password(body.current_password, rec["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    rec["password_hash"] = _hash_password(body.new_password)
    return {"status": "ok", "message": "Password updated"}
