from __future__ import annotations

import re


def parse_rent_yen(text: str | None) -> int | None:
    if not text:
        return None
    src = text.replace(",", "")
    man = re.search(r"(\d+(?:\.\d+)?)\s*万\s*(\d+)?", src)
    if man:
        base = float(man.group(1)) * 10000
        extra = int(man.group(2) or "0")
        return int(base + extra)
    yen = re.search(r"(\d{4,})\s*円?", src)
    if yen:
        return int(yen.group(1))
    return None
