"""
Demo zone / branch model: Southwest region with four zones and branch codes per state hub.
Used to scope compliance officer views and label reports.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

# region_key -> { zone_key: { "label", "branches": { code: state_label } } }
SOUTH_WEST: Dict[str, Any] = {
    "zone_1": {
        "label": "Southwest Zone 1",
        "branches": {
            "001": "Lagos (Ikeja hub)",
            "002": "Lagos (VI hub)",
        },
    },
    "zone_2": {
        "label": "Southwest Zone 2",
        "branches": {
            "003": "Ogun State",
            "004": "Oyo State",
        },
    },
    "zone_3": {
        "label": "Southwest Zone 3",
        "branches": {
            "005": "Osun State",
            "006": "Ondo State",
        },
    },
    "zone_4": {
        "label": "Southwest Zone 4",
        "branches": {
            "007": "Ekiti State",
        },
    },
}

REGIONS: Dict[str, Dict[str, Any]] = {
    "south_west": {
        "label": "Southwest",
        "zones": SOUTH_WEST,
    },
}


def _branch_zone_map() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for zk, zd in SOUTH_WEST.items():
        for code in zd.get("branches", {}):
            out[code] = zk
    return out


_BRANCH_TO_ZONE = _branch_zone_map()


def infer_zone_branch_for_customer(customer_id: str, region: str = "south_west") -> Tuple[str, str]:
    """Deterministic pseudo-assignment so demo customers spread across branches."""
    pairs: List[Tuple[str, str]] = []
    if region == "south_west":
        for zk, zd in SOUTH_WEST.items():
            for code in zd.get("branches", {}):
                pairs.append((zk, code))
    if not pairs:
        return "zone_1", "001"
    h = int(hashlib.sha256(customer_id.encode()).hexdigest(), 16)
    return pairs[h % len(pairs)]


def ensure_txn_aml_geo_metadata(metadata: Optional[Dict[str, Any]], customer_id: str) -> Dict[str, Any]:
    md = dict(metadata) if isinstance(metadata, dict) else {}
    region = str(md.get("aml_region") or "south_west")
    if not md.get("aml_zone") or not md.get("aml_branch_code"):
        z, b = infer_zone_branch_for_customer(customer_id, region)
        md.setdefault("aml_region", region)
        md.setdefault("aml_zone", z)
        md.setdefault("aml_branch_code", b)
    return md


def user_has_full_data_access(user: Dict[str, Any]) -> bool:
    role = (user.get("role") or "").strip().lower()
    if role in ("admin", "chief_compliance_officer"):
        return True
    sub = (user.get("sub") or "").strip().lower()
    if sub == "demo-user":
        return True
    return False


def _user_scope_lists(user: Dict[str, Any]) -> Tuple[Optional[str], List[str], List[str]]:
    region = user.get("aml_region")
    if isinstance(region, str) and region.strip():
        r = region.strip()
    else:
        r = None
    zones = user.get("aml_zones")
    branches = user.get("aml_branch_codes")
    zl = [str(x).strip() for x in zones] if isinstance(zones, list) else []
    bl = [str(x).strip() for x in branches] if isinstance(branches, list) else []
    zl = [x for x in zl if x]
    bl = [x for x in bl if x]
    return r, zl, bl


def txn_matches_user_scope(user: Dict[str, Any], metadata: Optional[Dict[str, Any]], customer_id: str) -> bool:
    if user_has_full_data_access(user):
        return True
    md = ensure_txn_aml_geo_metadata(metadata, customer_id)
    _, want_zones, want_branches = _user_scope_lists(user)
    if not want_zones and not want_branches:
        return True
    z = str(md.get("aml_zone") or "")
    b = str(md.get("aml_branch_code") or "")
    if want_branches and b not in want_branches:
        return False
    if want_zones and z not in want_zones:
        return False
    return True


def catalog_for_api() -> Dict[str, Any]:
    return {
        "regions": {
            k: {"label": v["label"], "zones": {zk: {"label": zv["label"], "branches": zv["branches"]} for zk, zv in v["zones"].items()}}
            for k, v in REGIONS.items()
        }
    }
