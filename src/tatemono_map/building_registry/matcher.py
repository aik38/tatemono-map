from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .normalization import normalize_building_input, strip_prefecture_prefix

NAME_SIMILARITY_THRESHOLD = 0.88


@dataclass(frozen=True)
class MatchResult:
    building_id: str | None
    reason: str
    candidate_ids: list[str]
    candidate_scores: list[float]


def _score_name(left: str, right: str) -> float:
    return SequenceMatcher(None, left or "", right or "").ratio()


def _format_top(candidates: list[tuple[str, float]]) -> tuple[list[str], list[float]]:
    ordered = sorted(candidates, key=lambda x: x[1], reverse=True)[:3]
    return [c[0] for c in ordered], [round(c[1], 4) for c in ordered]


def match_building(conn: Any, normalized_name: str, normalized_address: str) -> MatchResult:
    normalized_address = strip_prefecture_prefix(normalized_address)
    alias_rows = conn.execute(
        """
        SELECT s.building_id, s.raw_name
        FROM building_sources s
        WHERE s.raw_name IS NOT NULL AND s.raw_name <> ''
        """
    ).fetchall()
    alias_hits: list[str] = []
    for row in alias_rows:
        alias_norm = normalize_building_input(row[1], "").normalized_name
        if alias_norm and alias_norm == normalized_name and row[0] not in alias_hits:
            alias_hits.append(row[0])
    if len(alias_hits) == 1:
        return MatchResult(alias_hits[0], "alias_exact", [alias_hits[0]], [1.0])
    if len(alias_hits) > 1:
        return MatchResult(None, "alias_ambiguous", alias_hits[:3], [1.0 for _ in alias_hits[:3]])

    addr_rows = conn.execute(
        "SELECT building_id, norm_name, norm_address FROM buildings"
    ).fetchall()
    matched_addr_rows = [
        row for row in addr_rows if strip_prefecture_prefix(row[2] or "") == normalized_address
    ]
    if len(matched_addr_rows) == 1:
        return MatchResult(matched_addr_rows[0][0], "address_exact", [matched_addr_rows[0][0]], [1.0])
    if len(matched_addr_rows) > 1:
        scored = [(row[0], _score_name(normalized_name, row[1] or "")) for row in matched_addr_rows]
        top_ids, top_scores = _format_top(scored)
        best = sorted(scored, key=lambda x: x[1], reverse=True)
        if best and best[0][1] >= NAME_SIMILARITY_THRESHOLD and (len(best) == 1 or best[0][1] > best[1][1]):
            return MatchResult(best[0][0], "address_plus_name_similarity", top_ids, top_scores)
        return MatchResult(None, "address_candidates_low_confidence", top_ids, top_scores)

    return MatchResult(None, "unmatched", [], [])
