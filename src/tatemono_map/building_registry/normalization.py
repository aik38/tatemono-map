from __future__ import annotations

from dataclasses import dataclass

from tatemono_map.normalize.jp import normalize_address_jp, normalize_building_name


@dataclass(frozen=True)
class NormalizedBuilding:
    raw_name: str
    raw_address: str
    normalized_name: str
    normalized_address: str


def normalize_building_input(name: str | None, address: str | None) -> NormalizedBuilding:
    raw_name = (name or "").strip()
    raw_address = (address or "").strip()
    return NormalizedBuilding(
        raw_name=raw_name,
        raw_address=raw_address,
        normalized_name=normalize_building_name(raw_name),
        normalized_address=normalize_address_jp(raw_address),
    )
