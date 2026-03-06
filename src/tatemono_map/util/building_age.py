from __future__ import annotations

import re
from datetime import date

YEAR_MONTH_RE = re.compile(r"^(\d{4})[-/](\d{1,2})$")


def _parse_built_year_month(built_year_month: str | None) -> tuple[int, int] | None:
    text = (built_year_month or "").strip()
    if not text:
        return None

    match = YEAR_MONTH_RE.match(text)
    if not match:
        return None

    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        return None
    return year, month


def age_years_from_built_year_month(built_year_month: str | None, *, as_of: date | None = None) -> int | None:
    parsed = _parse_built_year_month(built_year_month)
    if parsed is None:
        return None
    year, month = parsed

    today = as_of or date.today()
    age = today.year - year
    if today.month < month:
        age -= 1
    return max(age, 0)


def built_year_month_is_future(built_year_month: str | None, *, as_of: date | None = None) -> bool:
    parsed = _parse_built_year_month(built_year_month)
    if parsed is None:
        return False
    year, month = parsed
    today = as_of or date.today()
    return year > today.year or (year == today.year and month > today.month)


def built_age_sort_rank(
    built_age_years: int | float | None,
    *,
    built_year_month: str | None,
    as_of: date | None = None,
) -> int:
    if built_year_month_is_future(built_year_month, as_of=as_of):
        return 0

    if isinstance(built_age_years, (int, float)):
        age = int(built_age_years)
        if age == 0:
            return 1
        if age > 0:
            return 2
    return 3
