from __future__ import annotations

import hashlib

from tatemono_map.util.text import normalize_text


def _sha1_hex(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def make_building_key(name: str, address: str) -> str:
    normalized_name = normalize_text(name)
    normalized_address = normalize_text(address)
    return _sha1_hex(f"{normalized_name}|{normalized_address}")


def make_listing_key_for_smartlink(source_url: str, room_label: str | None) -> str:
    normalized_room_label = normalize_text(room_label or "")
    return _sha1_hex(f"{source_url}|{normalized_room_label}")


def make_listing_key_for_master(raw_block: str) -> str:
    return _sha1_hex(raw_block)
