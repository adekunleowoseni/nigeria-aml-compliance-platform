from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.core.logging import get_logger

log = get_logger(component="sanctions_screening")

# OpenSanctions dataset search (public read API; optional API key for higher limits).
OPENSANCTIONS_SEARCH_URL = "https://api.opensanctions.org/search/default"


async def screen_name_opensanctions(name: str, *, limit: int = 8) -> Dict[str, Any]:
    """
    Query OpenSanctions consolidated dataset over the network (no local sanctions table required).
    Falls back gracefully if the service is unreachable or returns an error.
    """
    name = (name or "").strip()
    if len(name) < 2:
        return {
            "provider": "opensanctions",
            "query": name,
            "matches": [],
            "match_count": 0,
            "note": "Name too short for screening.",
        }

    headers: Dict[str, str] = {"Accept": "application/json"}
    if settings.opensanctions_api_key:
        headers["Authorization"] = f"Bearer {settings.opensanctions_api_key}"

    params: Dict[str, Any] = {"q": name, "limit": limit}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(OPENSANCTIONS_SEARCH_URL, params=params, headers=headers)
            if r.status_code == 401:
                return {
                    "provider": "opensanctions",
                    "query": name,
                    "matches": [],
                    "match_count": 0,
                    "note": "OpenSanctions returned 401; set OPENSANCTIONS_API_KEY if required.",
                }
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("sanctions_screen_failed", error=str(e))
        return {
            "provider": "opensanctions",
            "query": name,
            "matches": [],
            "match_count": 0,
            "note": f"Online sanctions search unavailable: {type(e).__name__}. Retry later or configure API access.",
        }

    # API shape varies; normalize common patterns
    results: List[Dict[str, Any]] = []
    raw_results = data.get("results") or data.get("entities") or data.get("data") or []
    if isinstance(raw_results, list):
        for item in raw_results[:limit]:
            if not isinstance(item, dict):
                continue
            caption = item.get("caption") or item.get("name") or item.get("schema")
            schema = item.get("schema") or item.get("datasets")
            tid = item.get("id")
            results.append(
                {
                    "id": tid,
                    "caption": caption,
                    "schema": schema,
                    "datasets": item.get("datasets"),
                    "countries": item.get("countries"),
                }
            )

    return {
        "provider": "opensanctions",
        "query": name,
        "matches": results,
        "match_count": len(results),
        "note": None if results else "No OpenSanctions entities returned for this query (not a clearance).",
    }
