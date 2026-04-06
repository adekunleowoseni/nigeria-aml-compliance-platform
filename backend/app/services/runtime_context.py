"""Process-wide handles for background tasks (e.g. transaction pipeline) that lack Request.app."""

from __future__ import annotations

from typing import Any, Optional

_pg: Optional[Any] = None


def set_postgres_client(pg: Optional[Any]) -> None:
    global _pg
    _pg = pg


def get_postgres_client_optional() -> Optional[Any]:
    return _pg
