from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .normalization import normalize_address_for_matching, normalize_building_input

NAME_SIMILARITY_THRESHOLD = 0.88
MATCH_SCORE_THRESHOLD = 0.91
UNIQUE_MARGIN = 0.02

RE_FUSED_BAN = re.compile(r"^(.*?)(\d{2,4})(?:番)?$")
MULTI_LOT_TOKENS = ("、", "〜")


@dataclass(frozen=True)
class MatchResult:
    building_id: str | None
    reason: str
    candidate_ids: list[str]
    candidate_scores: list[float]
    matched_address_variant: str = ""


def _score_name(left: str, right: str) -> float:
    return SequenceMatcher(None, left or "", right or "").ratio()


def _score_address(left: str, right: str) -> float:
    return SequenceMatcher(None, left or "", right or "").ratio()


def _format_top(candidates: list[tuple[str, float]]) -> tuple[list[str], list[float]]:
    ordered = sorted(candidates, key=lambda x: x[1], reverse=True)[:3]
    return [c[0] for c in ordered], [round(c[1], 4) for c in ordered]


def _address_variants(normalized_address: str) -> list[str]:
    base = normalize_address_for_matching(normalized_address)
    variants: list[str] = []

    def _add(value: str) -> None:
        val = normalize_address_for_matching(value)
        if val and val not in variants:
            variants.append(val)

    _add(base)
    if "、" in base:
        _add(base.split("、", 1)[0])
    if "〜" in base:
        _add(base.split("〜", 1)[0])

    fused = RE_FUSED_BAN.match(base)
    if fused and "-" not in fused.group(2):
        prefix, digits = fused.group(1), fused.group(2)
        if len(digits) == 2:
            _add(f"{prefix}{digits[0]}-{digits[1]}")
        elif len(digits) == 4:
            _add(f"{prefix}{digits[:2]}-{digits[2:]}")

    return variants


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def _has_multi_lot_or_range(address: str) -> bool:
    return any(token in address for token in MULTI_LOT_TOKENS)


def _pick_strong_unique(candidates: list[tuple[str, float, float, float]], variant: str) -> MatchResult:
    if not candidates:
        return MatchResult(None, "unmatched", [], [], variant)
    sorted_candidates = sorted(candidates, key=lambda x: x[1], reverse=True)
    top = [(cid, score) for cid, score, _n, _a in sorted_candidates]
    top_ids, top_scores = _format_top(top)
    best_id, best_score, best_name, best_addr = sorted_candidates[0]
    second_score = sorted_candidates[1][1] if len(sorted_candidates) > 1 else 0.0
    if (
        best_name >= NAME_SIMILARITY_THRESHOLD
        and best_addr >= 0.86
        and best_score >= MATCH_SCORE_THRESHOLD
        and best_score - second_score >= UNIQUE_MARGIN
    ):
        reason = "address_variant_match" if variant else "address_exact"
        return MatchResult(best_id, reason, top_ids, top_scores, variant)
    return MatchResult(None, "address_candidates_low_confidence", top_ids, top_scores, variant)


def match_building(conn: Any, normalized_name: str, normalized_address: str) -> MatchResult:
    if _has_multi_lot_or_range(normalized_address):
        return MatchResult(None, "address_multi_or_range", [], [])

    alias_rows = conn.execute(
        """
        SELECT s.building_id, s.raw_name, b.norm_address
        FROM building_sources s
        INNER JOIN buildings b ON b.building_id = s.building_id
        WHERE s.raw_name IS NOT NULL AND s.raw_name <> ''
        """
    ).fetchall()
    alias_hits: list[str] = []
    input_address_variants = set(_address_variants(normalized_address))
    for row in alias_rows:
        alias_norm = normalize_building_input(row[1], "").normalized_name
        source_addr = normalize_address_for_matching(row[2] or "")
        address_matches = bool(source_addr and source_addr in input_address_variants)
        if alias_norm and alias_norm == normalized_name and address_matches and row[0] not in alias_hits:
            alias_hits.append(row[0])
    if len(alias_hits) == 1:
        return MatchResult(alias_hits[0], "alias_exact", [alias_hits[0]], [1.0])
    if len(alias_hits) > 1:
        return MatchResult(None, "alias_ambiguous", alias_hits[:3], [1.0 for _ in alias_hits[:3]])

    addr_rows = conn.execute("SELECT building_id, norm_name, norm_address FROM buildings").fetchall()
    if not _has_digit(normalized_address):
        return MatchResult(None, "address_without_digits", [], [])

    for idx, variant in enumerate(_address_variants(normalized_address)):
        matched = [row for row in addr_rows if normalize_address_for_matching(row[2] or "") == variant]
        if not matched:
            continue
        if len(matched) == 1:
            name_score = _score_name(normalized_name, matched[0][1] or "")
            if idx == 0:
                return MatchResult(matched[0][0], "address_exact", [matched[0][0]], [round(name_score, 4)], variant)
            if name_score >= NAME_SIMILARITY_THRESHOLD:
                return MatchResult(matched[0][0], "address_variant_exact", [matched[0][0]], [round(name_score, 4)], variant)
            return MatchResult(None, "address_name_low_confidence", [matched[0][0]], [round(name_score, 4)], variant)

        scored = []
        for row in matched:
            name_score = _score_name(normalized_name, row[1] or "")
            addr_score = _score_address(variant, normalize_address_for_matching(row[2] or ""))
            total = name_score * 0.7 + addr_score * 0.3
            scored.append((row[0], total, name_score, addr_score))
        result = _pick_strong_unique(scored, variant if idx > 0 else "")
        if result.reason != "unmatched":
            return result

    return MatchResult(None, "unmatched", [], [])
