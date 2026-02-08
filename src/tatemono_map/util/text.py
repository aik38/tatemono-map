from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def compact_for_key(value: str | None) -> str:
    text = normalize_text(value).lower()
    return re.sub(r"[\s\-ー−‐,、。]", "", text)
