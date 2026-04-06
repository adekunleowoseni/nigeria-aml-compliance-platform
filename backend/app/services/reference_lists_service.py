"""Admin reference lists (sanctions, PEP, adverse media) with fuzzy name matching and batch screening."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree
from rapidfuzz import fuzz

from app.config import settings
from app.db.postgres_client import PostgresClient
from app.services import reference_lists_db as rldb

LIST_TYPES = frozenset({"sanctions", "pep", "adverse_media"})

_STORE: Dict[str, List[Dict[str, Any]]] = {
    "sanctions": [],
    "pep": [],
    "adverse_media": [],
}


def _threshold() -> int:
    return max(50, min(100, int(settings.reference_lists_fuzzy_threshold)))


def hydrate_from_db_rows(rows: Dict[str, List[Dict[str, Any]]]) -> None:
    for k in LIST_TYPES:
        _STORE[k] = list(rows.get(k) or [])


def get_counts() -> Dict[str, int]:
    return {k: len(_STORE[k]) for k in sorted(LIST_TYPES)}


def preview_list_items(list_type: str, limit: int) -> tuple[int, List[Dict[str, Any]]]:
    if list_type not in LIST_TYPES:
        raise ValueError("invalid list_type")
    items = _STORE.get(list_type) or []
    lim = max(0, min(limit, 500))
    return len(items), items[:lim]


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def best_fuzzy_score(query: str, candidate: str) -> int:
    q, c = _normalize(query), _normalize(candidate)
    if not q or not c:
        return 0
    return int(max(fuzz.WRatio(q, c), fuzz.token_set_ratio(q, c), fuzz.partial_ratio(q, c)))


def _aliases_from_record(rec: Dict[str, Any]) -> List[str]:
    al = rec.get("aliases")
    if al is None:
        al = rec.get("alias")
    if isinstance(al, str) and al.strip():
        return [al.strip()]
    if isinstance(al, list):
        return [str(x).strip() for x in al if str(x).strip()]
    return []


def _candidates_sanction(rec: Dict[str, Any]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    name = rec.get("name")
    if isinstance(name, str) and name.strip():
        out.append(("name", name))
    for i, a in enumerate(_aliases_from_record(rec)):
        out.append((f"alias_{i}", a))
    return out


def _associates_list(rec: Dict[str, Any]) -> List[Any]:
    ass = rec.get("associates") or rec.get("associate")
    if ass is None:
        return []
    if isinstance(ass, dict):
        return [ass]
    if isinstance(ass, list):
        return ass
    return []


def _candidates_pep(rec: Dict[str, Any]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    name = rec.get("name")
    if isinstance(name, str) and name.strip():
        out.append(("name", name))
    for i, row in enumerate(_associates_list(rec)):
        if isinstance(row, dict):
            an = row.get("name")
            if isinstance(an, str) and an.strip():
                out.append((f"associate_{i}", an))
    return out


def _candidates_adverse(rec: Dict[str, Any]) -> List[Tuple[str, str]]:
    subj = rec.get("subject")
    if isinstance(subj, str) and subj.strip():
        return [("subject", subj)]
    return []


def _match_list(customer_name: str, list_type: str, threshold: int) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for rec in _STORE.get(list_type, []):
        if list_type == "sanctions":
            pairs = _candidates_sanction(rec)
        elif list_type == "pep":
            pairs = _candidates_pep(rec)
        else:
            pairs = _candidates_adverse(rec)
        best = 0
        best_field = ""
        for field, cand in pairs:
            sc = best_fuzzy_score(customer_name, cand)
            if sc > best:
                best = sc
                best_field = field
        if best >= threshold:
            hits.append({"score": best, "matched_on": best_field, "record": rec})
    hits.sort(key=lambda x: int(x.get("score") or 0), reverse=True)
    return hits


def screen_customer_name(customer_name: str, threshold: Optional[int] = None) -> Dict[str, Any]:
    th = threshold if threshold is not None else _threshold()
    return {
        "sanctions": _match_list(customer_name, "sanctions", th),
        "pep": _match_list(customer_name, "pep", th),
        "adverse_media": _match_list(customer_name, "adverse_media", th),
        "fuzzy_threshold": th,
    }


def parse_json_bytes(raw: bytes) -> List[Dict[str, Any]]:
    data = json.loads(raw.decode("utf-8-sig"))
    if isinstance(data, dict):
        for key in ("items", "records", "data"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            raise ValueError("JSON must be an array or an object with items, records, or data array")
    if not isinstance(data, list):
        raise ValueError("JSON root must be an array")
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(data):
        if isinstance(row, dict):
            out.append(row)
        else:
            raise ValueError(f"Item {i} must be an object")
    return out


def _xml_local_name(tag: str) -> str:
    if "}" in tag:
        tag = tag.split("}", 1)[-1]
    return tag.lower().replace("-", "_")


def _append_scalar(d: Dict[str, Any], tag: str, val: str) -> None:
    if tag not in d:
        d[tag] = val
        return
    prev = d[tag]
    if isinstance(prev, list):
        prev.append(val)
    else:
        d[tag] = [prev, val]


def _element_to_simple_dict(el: etree._Element) -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    for child in el:
        tag = _xml_local_name(child.tag)
        subs = list(child)
        if not subs:
            txt = (child.text or "").strip()
            _append_scalar(d, tag, txt)
            continue
        sub_tags = [_xml_local_name(s.tag) for s in subs]
        if len(set(sub_tags)) == 1 and sub_tags[0] in ("associate", "alias", "item", "record", "row", "entry"):
            d[tag] = [_element_to_simple_dict(s) for s in subs]
        else:
            nested = _element_to_simple_dict(child)
            d[tag] = nested
    return d


def parse_xml_bytes(raw: bytes) -> List[Dict[str, Any]]:
    root = etree.fromstring(raw)
    root_name = _xml_local_name(root.tag)
    record_tags = {"item", "record", "row", "entry", "entity", "sanction", "pep", "incident"}
    loose_container = root_name in {"items", "records", "list", "array", "root", "reference_lists", "data"}
    children = list(root)
    if children and all(_xml_local_name(c.tag) in record_tags for c in children):
        candidates = children
    elif loose_container and children:
        candidates = children
    else:
        candidates = [root]
    out: List[Dict[str, Any]] = []
    for el in candidates:
        t = _xml_local_name(el.tag)
        if t in {"items", "records", "list"}:
            for sub in el:
                out.append(_element_to_simple_dict(sub))
        elif t in record_tags or len(el) > 0:
            out.append(_element_to_simple_dict(el))
    if not out:
        out.append(_element_to_simple_dict(root))
    return out


def parse_upload(raw: bytes, *, content_type: Optional[str], filename: Optional[str]) -> List[Dict[str, Any]]:
    ct = (content_type or "").lower()
    fn = (filename or "").lower()
    if "json" in ct or fn.endswith(".json"):
        return parse_json_bytes(raw)
    if "xml" in ct or fn.endswith(".xml") or fn.endswith(".xhtml"):
        return parse_xml_bytes(raw)
    s = raw.lstrip()
    if s.startswith(b"[") or s.startswith(b"{"):
        return parse_json_bytes(raw)
    if s.startswith(b"<"):
        return parse_xml_bytes(raw)
    raise ValueError("Could not detect format; use JSON or XML body, or set filename extension / Content-Type")


async def replace_list(
    pg: Optional[PostgresClient],
    list_type: str,
    items: List[Dict[str, Any]],
    updated_by: str,
) -> None:
    if list_type not in LIST_TYPES:
        raise ValueError("list_type must be sanctions, pep, or adverse_media")
    _STORE[list_type] = list(items)
    if pg is not None:
        await rldb.upsert_list(pg, list_type=list_type, items=items, updated_by=updated_by)


async def load_from_database(pg: PostgresClient) -> None:
    rows = await rldb.load_all_lists(pg)
    hydrate_from_db_rows(rows)


async def run_full_customer_screening_scan(
    pg: Optional[PostgresClient],
    *,
    persist: bool = True,
) -> Dict[str, Any]:
    from app.services.customer_kyc_db import list_customers_kyc

    rows, total = await list_customers_kyc(
        pg,
        limit=100_000,
        offset=0,
        q=None,
        merge_demo_sources=True,
    )
    th = _threshold()
    hits: List[Dict[str, Any]] = []
    for r in rows:
        cid = str(r.get("customer_id") or "")
        name = str(r.get("customer_name") or "")
        if not name.strip():
            continue
        local = screen_customer_name(name, th)
        n = len(local["sanctions"]) + len(local["pep"]) + len(local["adverse_media"])
        if n == 0:
            continue
        hits.append(
            {
                "customer_id": cid,
                "customer_name": name,
                "sanctions": local["sanctions"][:5],
                "pep": local["pep"][:5],
                "adverse_media": local["adverse_media"][:5],
            }
        )
    hits.sort(
        key=lambda h: max(
            int((h["sanctions"][0]["score"]) if h["sanctions"] else 0),
            int((h["pep"][0]["score"]) if h["pep"] else 0),
            int((h["adverse_media"][0]["score"]) if h["adverse_media"] else 0),
        ),
        reverse=True,
    )
    store_cap = 500
    summary = {
        "customers_scanned": len(rows),
        "customer_rows_reported_total": total,
        "hits_total": len(hits),
        "fuzzy_threshold": th,
        "hits": hits[:store_cap],
        "hits_truncated": len(hits) > store_cap,
    }
    if persist and pg is not None:
        try:
            await rldb.insert_screening_run(
                pg,
                customers_scanned=len(rows),
                hits_total=len(hits),
                hits=hits[:store_cap],
                notes=None,
            )
        except Exception:
            from app.core.logging import get_logger

            get_logger(component="reference_lists").exception("reference_screening_run_persist_failed")
    return summary
