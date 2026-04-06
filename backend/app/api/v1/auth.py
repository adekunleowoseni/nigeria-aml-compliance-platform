from __future__ import annotations

from typing import Any, Dict, List, Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.core.security import create_access_token, get_current_user, require_admin
from app.services import audit_trail
from app.services.zone_branch import catalog_for_api

router = APIRouter(prefix="/auth")


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


ADMIN_EMAIL = "admin@admin.com"
ADMIN_DEFAULT_PASSWORD = "12345678"
CCO_EMAIL = "cco@demo.com"
COMPLIANCE_SW_EMAIL = "compliance.sw@demo.com"


def _user_token_extra(rec: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "role": rec["role"],
        "email": rec["email"],
        "display_name": rec.get("display_name") or rec["email"].split("@")[0],
    }
    r = rec.get("aml_region")
    if isinstance(r, str) and r.strip():
        out["aml_region"] = r.strip()
    z = rec.get("aml_zones")
    if isinstance(z, list) and z:
        out["aml_zones"] = [str(x).strip() for x in z if str(x).strip()]
    b = rec.get("aml_branch_codes")
    if isinstance(b, list) and b:
        out["aml_branch_codes"] = [str(x).strip() for x in b if str(x).strip()]
    return out


def _user_public(rec: Dict[str, Any]) -> Dict[str, Any]:
    u = {k: v for k, v in rec.items() if k != "password_hash"}
    return u


# In-memory users (demo). Password is bcrypt-hashed.
_users: Dict[str, Dict[str, Any]] = {
    ADMIN_EMAIL.lower(): {
        "email": ADMIN_EMAIL,
        "password_hash": _hash_password(ADMIN_DEFAULT_PASSWORD),
        "role": "admin",
        "display_name": "Administrator",
    },
    CCO_EMAIL.lower(): {
        "email": CCO_EMAIL,
        "password_hash": _hash_password(ADMIN_DEFAULT_PASSWORD),
        "role": "chief_compliance_officer",
        "display_name": "Chief Compliance Officer",
    },
    COMPLIANCE_SW_EMAIL.lower(): {
        "email": COMPLIANCE_SW_EMAIL,
        "password_hash": _hash_password(ADMIN_DEFAULT_PASSWORD),
        "role": "compliance_officer",
        "display_name": "Southwest Compliance Officer",
        "aml_region": "south_west",
        "aml_zones": ["zone_1", "zone_2"],
        "aml_branch_codes": ["001", "002", "003"],
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


class UpdateAssignmentsBody(BaseModel):
    """Compliance / CCO may update their own zone & branch scope (demo)."""

    aml_region: str = Field("south_west", min_length=3, max_length=64)
    aml_zones: List[str] = Field(default_factory=list)
    aml_branch_codes: List[str] = Field(default_factory=list)


class AdminCreateUserBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: str = Field(..., min_length=3, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    aml_region: Optional[str] = None
    aml_zones: List[str] = Field(default_factory=list)
    aml_branch_codes: List[str] = Field(default_factory=list)


class AdminPatchUserBody(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    aml_region: Optional[str] = None
    aml_zones: Optional[List[str]] = None
    aml_branch_codes: Optional[List[str]] = None


@router.get("/catalog/zones")
async def zones_catalog(user: Dict[str, Any] = Depends(get_current_user)):
    """Southwest zones and branch codes for assignment UI."""
    return catalog_for_api()


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginBody) -> LoginResponse:
    key = body.email.strip().lower()
    user = _users.get(key)
    if not user or not _verify_password(body.password, user["password_hash"]):
        audit_trail.record_login_failure(attempted_email=key, reason="invalid_credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    audit_trail.record_login_success(
        email=user["email"],
        role=str(user.get("role") or ""),
        display_name=str(user.get("display_name") or ""),
    )
    token = create_access_token(user["email"], extra=_user_token_extra(user))
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=_user_public(user),
    )


@router.get("/me")
async def me(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    email = (user.get("email") or user.get("sub") or "").strip().lower()
    rec = _users.get(email)
    base = {
        "sub": user.get("sub"),
        "email": user.get("email") or user.get("sub"),
        "role": user.get("role"),
        "aml_region": user.get("aml_region"),
        "aml_zones": user.get("aml_zones"),
        "aml_branch_codes": user.get("aml_branch_codes"),
    }
    if rec:
        base["display_name"] = rec.get("display_name")
        base["aml_region"] = rec.get("aml_region") or base.get("aml_region")
        base["aml_zones"] = rec.get("aml_zones") or base.get("aml_zones")
        base["aml_branch_codes"] = rec.get("aml_branch_codes") or base.get("aml_branch_codes")
    return base


@router.patch("/me/assignments", response_model=LoginResponse)
async def update_my_assignments(body: UpdateAssignmentsBody, user: Dict[str, Any] = Depends(get_current_user)):
    role = (user.get("role") or "").strip().lower()
    if role not in ("compliance_officer", "chief_compliance_officer"):
        raise HTTPException(status_code=403, detail="Only compliance or CCO roles may update zone/branch scope.")
    email = (user.get("email") or user.get("sub") or "").strip().lower()
    rec = _users.get(email)
    if not rec:
        raise HTTPException(status_code=404, detail="User record not found")
    rec["aml_region"] = body.aml_region.strip()
    rec["aml_zones"] = [str(z).strip() for z in body.aml_zones if str(z).strip()]
    rec["aml_branch_codes"] = [str(b).strip() for b in body.aml_branch_codes if str(b).strip()]
    token = create_access_token(rec["email"], extra=_user_token_extra(rec))
    audit_trail.record_event_from_user(
        user,
        action="config.user.assignments_updated",
        resource_type="user",
        resource_id=email,
        details={"aml_region": rec.get("aml_region"), "zones": rec.get("aml_zones"), "branches": rec.get("aml_branch_codes")},
    )
    return LoginResponse(access_token=token, token_type="bearer", user=_user_public(rec))


@router.get("/admin/users", response_model=Dict[str, Any])
async def admin_list_users(user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    items = [_user_public(u) for u in _users.values()]
    return {"items": items, "total": len(items)}


@router.post("/admin/users", response_model=Dict[str, Any])
async def admin_create_user(body: AdminCreateUserBody, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    key = body.email.strip().lower()
    if key in _users:
        raise HTTPException(status_code=400, detail="User already exists")
    rec: Dict[str, Any] = {
        "email": str(body.email).strip().lower(),
        "password_hash": _hash_password(body.password),
        "role": body.role.strip(),
        "display_name": body.display_name.strip(),
    }
    if body.aml_region:
        rec["aml_region"] = body.aml_region.strip()
    if body.aml_zones:
        rec["aml_zones"] = [str(z).strip() for z in body.aml_zones if str(z).strip()]
    if body.aml_branch_codes:
        rec["aml_branch_codes"] = [str(b).strip() for b in body.aml_branch_codes if str(b).strip()]
    _users[key] = rec
    audit_trail.record_event_from_user(
        user,
        action="admin.user.created",
        resource_type="user",
        resource_id=key,
        details={"role": rec.get("role"), "display_name": rec.get("display_name")},
    )
    return {"status": "ok", "user": _user_public(rec)}


@router.patch("/admin/users/{email}", response_model=Dict[str, Any])
async def admin_patch_user(
    email: str,
    body: AdminPatchUserBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    require_admin(user)
    key = email.strip().lower()
    rec = _users.get(key)
    if not rec:
        raise HTTPException(status_code=404, detail="User not found")
    if body.display_name is not None:
        rec["display_name"] = body.display_name.strip()
    if body.role is not None:
        rec["role"] = body.role.strip()
    if body.password is not None:
        rec["password_hash"] = _hash_password(body.password)
    if body.aml_region is not None:
        rec["aml_region"] = body.aml_region.strip() or None
        if not rec["aml_region"]:
            rec.pop("aml_region", None)
    if body.aml_zones is not None:
        rec["aml_zones"] = [str(z).strip() for z in body.aml_zones if str(z).strip()]
    if body.aml_branch_codes is not None:
        rec["aml_branch_codes"] = [str(b).strip() for b in body.aml_branch_codes if str(b).strip()]
    audit_trail.record_event_from_user(
        user,
        action="admin.user.updated",
        resource_type="user",
        resource_id=key,
        details={
            "display_name": rec.get("display_name"),
            "role": rec.get("role"),
            "password_rotated": body.password is not None,
        },
    )
    return {"status": "ok", "user": _user_public(rec)}


@router.delete("/admin/users/{email}")
async def admin_delete_user(email: str, user: Dict[str, Any] = Depends(get_current_user)):
    require_admin(user)
    key = email.strip().lower()
    if key not in _users:
        raise HTTPException(status_code=404, detail="User not found")
    if key == ADMIN_EMAIL.lower():
        raise HTTPException(status_code=400, detail="Cannot delete primary admin account")
    del _users[key]
    audit_trail.record_event_from_user(
        user,
        action="admin.user.deleted",
        resource_type="user",
        resource_id=key,
        details={},
    )
    return {"status": "ok"}


class WorkflowSettingsBody(BaseModel):
    """Admin-only shortcuts for demo/training. Defaults require CO escalation and CCO approval."""

    cco_auto_approve_otc_reporting: bool = False
    cco_auto_approve_str_on_escalation: bool = False


@router.get("/admin/workflow-settings")
async def admin_get_workflow_settings(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    require_admin(user)
    return {
        "cco_auto_approve_otc_reporting": bool(getattr(settings, "cco_auto_approve_otc_reporting", False)),
        "cco_auto_approve_str_on_escalation": bool(getattr(settings, "cco_auto_approve_str_on_escalation", False)),
        "description": (
            "When both flags are off (default), OTC true-positive reports need CCO approval after CO escalation; "
            "STR needs CCO approval after escalation. Turning a flag on relaxes that path for demo use only."
        ),
    }


@router.put("/admin/workflow-settings")
async def admin_put_workflow_settings(
    body: WorkflowSettingsBody,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    require_admin(user)
    settings.cco_auto_approve_otc_reporting = bool(body.cco_auto_approve_otc_reporting)
    settings.cco_auto_approve_str_on_escalation = bool(body.cco_auto_approve_str_on_escalation)
    audit_trail.record_event_from_user(
        user,
        action="admin.workflow_settings.updated",
        resource_type="configuration",
        resource_id="workflow",
        details={
            "cco_auto_approve_otc_reporting": settings.cco_auto_approve_otc_reporting,
            "cco_auto_approve_str_on_escalation": settings.cco_auto_approve_str_on_escalation,
        },
    )
    return {
        "status": "ok",
        "cco_auto_approve_otc_reporting": settings.cco_auto_approve_otc_reporting,
        "cco_auto_approve_str_on_escalation": settings.cco_auto_approve_str_on_escalation,
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
        audit_trail.record_event_from_user(
            user,
            action="auth.password_change.failure",
            resource_type="identity",
            resource_id=email,
            details={"reason": "current_password_mismatch"},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    rec["password_hash"] = _hash_password(body.new_password)
    audit_trail.record_event_from_user(
        user,
        action="user.password_changed",
        resource_type="identity",
        resource_id=email,
        details={},
    )
    return {"status": "ok", "message": "Password updated"}


def list_assignable_case_review_analysts() -> List[str]:
    """Emails eligible for periodic closed-case review assignment (compliance roles; demo user directory)."""
    emails: List[str] = []
    for rec in _users.values():
        role = (rec.get("role") or "").lower()
        if role in ("compliance_officer", "chief_compliance_officer"):
            emails.append(str(rec["email"]).strip().lower())
    return sorted(set(emails))
