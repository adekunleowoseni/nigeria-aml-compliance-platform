from __future__ import annotations

from pydantic import BaseModel


class User(BaseModel):
    id: str
    username: str
    roles: list[str] = []

