from __future__ import annotations

import hashlib
import uuid


def make_alias_key(normalized_name: str, normalized_address: str) -> str:
    material = f"{normalized_name}|{normalized_address}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, material))


def make_legacy_alias_key(normalized_name: str, normalized_address: str) -> str:
    material = f"{normalized_name}|{normalized_address}"
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:32]

