from __future__ import annotations

import re
from difflib import SequenceMatcher

from tatemono_map.buildings_master.from_sources import normalize_address_jp, normalize_building_name

WARD_RE = re.compile(r"(門司区|小倉北区|小倉南区|戸畑区|八幡東区|八幡西区|若松区)")
CITY_RE = re.compile(r"(北九州市[^\d\- ]*|福岡市[^\d\- ]*)")


def normalize_name(value: str | None) -> str:
    return normalize_building_name(value or "")


def normalize_address(value: str | None) -> str:
    return normalize_address_jp(value or "")


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
