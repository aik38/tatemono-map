from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from functools import lru_cache

from .normalization import normalize_address_for_matching, normalize_building_input, normalize_ulucks_name

NAME_SIMILARITY_THRESHOLD = 0.88
MATCH_SCORE_THRESHOLD = 0.91
UNIQUE_MARGIN = 0.02

RE_FUSED_BAN = re.compile(r"^(.*?)(\d{2,4})(?:番)?$")
RE_SERIES_SUFFIX = re.compile(r"(?:\s|-)?(?:(\d{1,2})|(VIII|VII|VI|IV|III|II|IX|X|V|I))$")
MULTI_LOT_TOKENS = ("、", "〜")


@lru_cache(maxsize=65536)
def _matching_address(value: str) -> str:
    return normalize_address_for_matching(value)


@lru_cache(maxsize=65536)
def _alias_name(value: str) -> str:
    return normalize_building_input(value, '').normalized_name


@lru_cache(maxsize=65536)
def _ulucks_name(value: str) -> str:
    return normalize_ulucks_name(value)


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
    base = _matching_address(normalized_address)
    variants: list[str] = []

    def _add(value: str) -> None:
        val = _matching_address(value)
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


def _extract_series_suffix(name: str) -> int | str | None:
    block = re.search(r'(?:第)?([A-Z]+|[0-9]+)(?:号?棟|号館)$', (name or '').upper())
    if block:
        token=block[1]
        return int(token) if token.isdigit() else token
    letter = re.search(r'(?:[\s\-・]|[一-龥ぁ-んァ-ヺ])([A-Z])$', (name or '').upper())
    if letter:
        return letter[1]
    annex = re.search(r'(本館|別館|新館|東館|西館|南館|北館)$',name or '')
    if annex:
        return annex[1]
    match = RE_SERIES_SUFFIX.search((name or "").upper())
    if not match:
        return None
    numeric, roman = match.groups()
    if numeric:
        return int(numeric)
    if roman:
        return {"I":1,"II":2,"III":3,"IV":4,"V":5,"VI":6,"VII":7,"VIII":8,"IX":9,"X":10}.get(roman)
    return None


def _has_series_suffix_conflict(left_name: str, right_name: str, *, strict=False) -> bool:
    left_suffix = _extract_series_suffix(left_name)
    right_suffix = _extract_series_suffix(right_name)
    if strict and (left_suffix is None) != (right_suffix is None):
        return True
    return left_suffix is not None and right_suffix is not None and left_suffix != right_suffix


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


def _pick_equivalent_duplicate(
    candidates: list[tuple[str, str, str]],
    *,
    normalized_name: str,
    normalized_address: str,
    variant: str,
) -> MatchResult | None:
    if len(candidates) < 2:
        return None
    if not normalized_name or not normalized_address:
        return None
    if any((name or "") != normalized_name for _building_id, name, _addr in candidates):
        return None
    if any((addr or "") != normalized_address for _building_id, _name, addr in candidates):
        return None
    picked_id = sorted(building_id for building_id, _name, _addr in candidates)[0]
    candidate_ids = [building_id for building_id, _name, _addr in sorted(candidates, key=lambda row: row[0])[:3]]
    candidate_scores = [1.0 for _ in candidate_ids]
    return MatchResult(picked_id, "address_equivalent_duplicate", candidate_ids, candidate_scores, variant)


def match_building(conn: Any, normalized_name: str, normalized_address: str, *, source_address_aliases: bool = False) -> MatchResult:
    if not normalized_name or '\ufffd' in normalized_name or any(ord(ch)<32 for ch in normalized_name):
        return MatchResult(None, "invalid_building_name", [], [])
    alias_name = _ulucks_name if source_address_aliases else _alias_name
    if source_address_aliases:
        # A prior source may carry a verified full address that differs from
        # the immutable canonical address. Require the complete name/address
        # pair and a unique canonical ID; never infer a ward from a name.
        source_hits = set()
        address = _matching_address(normalized_address)
        rows = conn.execute(
            "SELECT s.building_id,s.raw_name,s.raw_address,b.norm_address FROM building_sources s JOIN buildings b ON b.building_id=s.building_id WHERE s.raw_name<>''"
        ).fetchall()
        for building, name, raw_address, canonical_address in rows:
            if raw_address and alias_name(name) == normalized_name and _matching_address(raw_address) == address:
                source_hits.add(building)
        if source_hits:
            # Do not let a historical source alias override another exact
            # canonical/source-name identity at the incoming address.
            for building, name, raw_address, canonical_address in rows:
                if alias_name(name) == normalized_name and _matching_address(canonical_address or '') == address:
                    source_hits.add(building)
            for building, name, canonical_address in conn.execute(
                "SELECT building_id,canonical_name,norm_address FROM buildings"
            ):
                if alias_name(name or '') == normalized_name and _matching_address(canonical_address or '') == address:
                    source_hits.add(building)
        if len(source_hits) == 1:
            building = next(iter(source_hits))
            return MatchResult(building, "source_address_alias_exact", [building], [1.0])
        if source_hits:
            ids = sorted(source_hits)[:3]
            return MatchResult(None, "alias_ambiguous", ids, [1.0] * len(ids))
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
        alias_norm = alias_name(row[1])
        source_addr = _matching_address(row[2] or "")
        address_matches = bool(source_addr and source_addr in input_address_variants)
        if alias_norm and alias_norm == normalized_name and address_matches and row[0] not in alias_hits:
            alias_hits.append(row[0])
    if len(alias_hits) == 1:
        return MatchResult(alias_hits[0], "alias_exact", [alias_hits[0]], [1.0])
    if len(alias_hits) > 1:
        return MatchResult(None, "alias_ambiguous", alias_hits[:3], [1.0 for _ in alias_hits[:3]])

    addr_rows = conn.execute("SELECT building_id, " + ("canonical_name" if source_address_aliases else "norm_name") + ", norm_address FROM buildings").fetchall()
    if source_address_aliases:
        addr_rows = [(building, alias_name(name or ''), address) for building, name, address in addr_rows]
    if not _has_digit(normalized_address):
        return MatchResult(None, "address_without_digits", [], [])

    for idx, variant in enumerate(_address_variants(normalized_address)):
        matched = [row for row in addr_rows if _matching_address(row[2] or "") == variant]
        if not matched:
            continue
        equivalent_duplicate = _pick_equivalent_duplicate(
            [(row[0], row[1] or "", _matching_address(row[2] or "")) for row in matched],
            normalized_name=normalized_name,
            normalized_address=variant,
            variant=variant if idx > 0 else "",
        )
        if equivalent_duplicate is not None:
            return equivalent_duplicate
        if len(matched) == 1:
            name_score = _score_name(normalized_name, matched[0][1] or "")
            if _has_series_suffix_conflict(normalized_name, matched[0][1] or "", strict=True):
                return MatchResult(None, "name_suffix_conflict", [matched[0][0]], [round(name_score, 4)], variant)
            if name_score < NAME_SIMILARITY_THRESHOLD:
                return MatchResult(None, "address_name_low_confidence", [matched[0][0]], [round(name_score,4)], variant)
            if idx == 0:
                return MatchResult(matched[0][0], "address_exact", [matched[0][0]], [round(name_score, 4)], variant)
            if name_score >= NAME_SIMILARITY_THRESHOLD:
                return MatchResult(matched[0][0], "address_variant_exact", [matched[0][0]], [round(name_score, 4)], variant)
            return MatchResult(None, "address_name_low_confidence", [matched[0][0]], [round(name_score, 4)], variant)

        scored = []
        for row in matched:
            name_score = _score_name(normalized_name, row[1] or "")
            addr_score = _score_address(variant, _matching_address(row[2] or ""))
            total = name_score * 0.7 + addr_score * 0.3
            if _has_series_suffix_conflict(normalized_name, row[1] or "", strict=True):
                continue
            scored.append((row[0], total, name_score, addr_score))
        result = _pick_strong_unique(scored, variant if idx > 0 else "")
        if result.reason != "unmatched":
            return result

    return MatchResult(None, "unmatched", [], [])
