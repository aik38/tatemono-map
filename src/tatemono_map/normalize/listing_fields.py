from __future__ import annotations

import re
from datetime import date, datetime

IMMEDIATE_RE = re.compile(r"即(?:\s*入(?:居|可)?)?")
DATE_MD_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")
BUILT_YM_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
BUILT_AGE_RE = re.compile(r"\(\s*(\d+)\s*年\s*\)")


def parse_reference_date(value: str | None) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def normalize_built(raw: str | None) -> tuple[str | None, int | None]:
    text = (raw or "").strip()
    if not text:
        return None, None
    ym = None
    years = None
    m = BUILT_YM_RE.search(text)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        if 1 <= month <= 12:
            ym = f"{year:04d}-{month:02d}"
    a = BUILT_AGE_RE.search(text)
    if a:
        years = int(a.group(1))
    return ym, years


def normalize_availability(
    raw: str | None,
    reference_date: str | None,
    category: str | None = None,
) -> tuple[bool, str | None, str | None]:
    text = (raw or "").strip()
    if not text:
        if (category or "").strip().lower() == "ulucks":
            return True, "即入", None
        return False, None, None

    if IMMEDIATE_RE.search(text):
        return True, "即入居", None

    m = DATE_MD_RE.search(text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        ref = parse_reference_date(reference_date)
        if not ref:
            return False, text, None
        year = ref.year
        if month < ref.month:
            year += 1
        try:
            d = date(year, month, day)
        except ValueError:
            return False, text, None
        return False, f"{month}/{day}", d.isoformat()

    return False, text, None
