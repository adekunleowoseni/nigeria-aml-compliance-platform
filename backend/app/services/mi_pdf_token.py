"""HMAC-signed short-lived tokens for Board pack PDF download (no session)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

from app.config import settings


def _secret() -> bytes:
    return (settings.jwt_secret_key or "change-me").encode("utf-8")


def sign_board_pdf_download(*, ttl_seconds: int = 900) -> tuple[str, int]:
    exp = int(time.time()) + max(60, int(ttl_seconds))
    payload = {"k": "board_pack", "exp": exp}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_secret(), body, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(body + b"." + sig).decode("ascii").rstrip("=")
    return token, exp


def verify_board_pdf_token(token: str) -> Optional[Dict[str, Any]]:
    if not token or not token.strip():
        return None
    pad = "=" * ((4 - len(token) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(token.strip() + pad)
    except Exception:
        return None
    if b"." not in raw:
        return None
    body, sig = raw.rsplit(b".", 1)
    expect = hmac.new(_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    if payload.get("k") != "board_pack":
        return None
    exp = int(payload.get("exp") or 0)
    if exp < int(time.time()):
        return None
    return payload
