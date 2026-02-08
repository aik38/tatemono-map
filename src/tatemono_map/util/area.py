from __future__ import annotations

import re


def parse_area_sqm(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:㎡|m2|m\^2)", text, re.IGNORECASE)
    return float(m.group(1)) if m else None
