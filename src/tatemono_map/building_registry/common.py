from __future__ import annotations

import re
import sqlite3
from difflib import SequenceMatcher

from .normalization import normalize_building_input

WARD_RE = re.compile(r"(門司区|小倉北区|小倉南区|戸畑区|八幡東区|八幡西区|若松区)")
CITY_RE = re.compile(r"(北九州市[^\d\- ]*|福岡市[^\d\- ]*)")


def normalize_name(value: str | None) -> str:
    return normalize_building_input(value, "").normalized_name


def normalize_address(value: str | None) -> str:
    return normalize_building_input("", value).normalized_address


def ward_or_city(address: str | None) -> str:
    text = address or ""
    ward = WARD_RE.search(text)
    if ward:
        return ward.group(1)
    city = CITY_RE.search(text)
    if city:
        return city.group(1)
    return ""


def fuzzy_score(name_a: str, addr_a: str, name_b: str, addr_b: str) -> float:
    name_score = SequenceMatcher(None, name_a, name_b).ratio()
    addr_score = SequenceMatcher(None, addr_a, addr_b).ratio()
    return name_score * 0.6 + addr_score * 0.4


def normalize_source_name(source: str | None, *, category: str | None = None) -> str:
    tokens = " ".join(filter(None, [(source or "").strip().lower(), (category or "").strip().lower()]))
    if "ulucks" in tokens:
        return "ulucks"
    if "realpro" in tokens:
        return "realpro"
    if "mansion_review" in tokens and "chintai" in tokens:
        return "mansion_review_chintai"
    if "mansion_review" in tokens and "mansion" in tokens:
        return "mansion_review_mansion"
    if "chintai" in tokens:
        return "mansion_review_chintai"
    if "mansion" in tokens:
        return "mansion_review_mansion"
    return (source or "").strip().lower() or "unknown"


def source_domain(normalized_source: str) -> str:
    if normalized_source in {"ulucks", "realpro", "mansion_review_chintai"}:
        return "rental"
    if normalized_source in {"mansion_review_mansion"}:
        return "sale"
    if normalized_source.startswith("mansion_review"):
        return "facts"
    return "unknown"


def insert_unmatched_queue(
    conn: sqlite3.Connection,
    *,
    source: str,
    ingest_run_id: int | None,
    evidence_id: str,
    raw_name: str,
    raw_address: str,
    normalized_name: str,
    normalized_address: str,
    reason: str,
    candidate_building_ids: str = "",
    candidate_scores: str = "",
    domain: str | None = None,
) -> None:
    normalized_source = normalize_source_name(source)
    resolved_domain = domain or source_domain(normalized_source)
    conn.execute(
        """
        INSERT INTO unmatched_queue(
            domain, source, ingest_run_id, evidence_id,
            raw_name, raw_address, normalized_name, normalized_address,
            reason, candidate_building_ids, candidate_scores, status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', CURRENT_TIMESTAMP)
        """,
        (
            resolved_domain,
            normalized_source,
            ingest_run_id,
            evidence_id,
            raw_name,
            raw_address,
            normalized_name,
            normalized_address,
            reason,
            candidate_building_ids,
            candidate_scores,
        ),
    )
