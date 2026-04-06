from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings


bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(subject: str, extra: Dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: Dict[str, Any] = {"sub": subject, "iat": int(now.timestamp()), "exp": int(expire.timestamp())}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e


def _default_dev_user() -> Dict[str, Any]:
    return {"sub": "demo-user", "role": "compliance_officer"}


def require_admin(user: Dict[str, Any]) -> None:
    role = (user.get("role") or "").strip().lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required.",
        )


def require_cco_or_admin(user: Dict[str, Any]) -> None:
    """STR approval queue: only CCO or admin may approve escalations for filing."""
    role = (user.get("role") or "").strip().lower()
    if role not in ("admin", "chief_compliance_officer"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chief Compliance Officer or Administrator role required for this action.",
        )


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Dict[str, Any]:
    if creds is None:
        if (
            settings.allow_anonymous_dev
            and settings.app_env.strip().lower() == "development"
        ):
            user = _default_dev_user()
            request.state.user = user
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    payload = _decode_token(creds.credentials)
    request.state.user = payload
    return payload


async def get_current_user_or_retention_internal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_retention_internal_key: Optional[str] = Header(None, alias="X-Retention-Internal-Key"),
) -> Dict[str, Any]:
    """
    Same as ``get_current_user`` unless ``X-Retention-Internal-Key`` matches
    ``settings.retention_internal_api_key`` (for Celery Beat → run-now without a JWT).
    """
    ik = (x_retention_internal_key or "").strip()
    rk = (settings.retention_internal_api_key or "").strip()
    if rk and ik == rk:
        user = {"sub": "retention-internal", "role": "admin", "email": "celery@internal"}
        request.state.user = user
        return user
    return await get_current_user(request, creds)


async def get_current_user_or_reference_internal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_reference_lists_internal_key: Optional[str] = Header(None, alias="X-Reference-Lists-Internal-Key"),
) -> Dict[str, Any]:
    """
    Bearer JWT or ``X-Reference-Lists-Internal-Key`` matching ``reference_lists_internal_api_key``
    (or ``retention_internal_api_key`` if the former is unset) for scheduled full-database screening.
    """
    ik = (x_reference_lists_internal_key or "").strip()
    rk = (settings.reference_lists_internal_api_key or "").strip()
    fb = (settings.retention_internal_api_key or "").strip()
    secret = rk or fb
    if secret and ik == secret:
        user = {"sub": "reference-lists-internal", "role": "admin", "email": "celery@reference-lists"}
        request.state.user = user
        return user
    return await get_current_user(request, creds)


async def get_current_user_or_mi_internal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_mi_internal_key: Optional[str] = Header(None, alias="X-MI-Internal-Key"),
) -> Dict[str, Any]:
    """Bearer JWT or ``X-MI-Internal-Key`` matching MI / retention internal ops key."""
    ik = (x_mi_internal_key or "").strip()
    mk = (settings.mi_schedule_internal_api_key or "").strip()
    rk = (settings.retention_internal_api_key or "").strip()
    secret = mk or rk
    if secret and ik == secret:
        user = {"sub": "mi-internal", "role": "admin", "email": "celery@mi-internal"}
        request.state.user = user
        return user
    return await get_current_user(request, creds)

