from __future__ import annotations

import re
from datetime import date

YEAR_MONTH_RE = re.compile(r"^(\d{4})[-/](\d{1,2})$")


def age_years_from_built_year_month(built_year_month: str | None, *, as_of: date | None = None) -> int | None:
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

    today = as_of or date.today()
    age = today.year - year
    if today.month < month:
        age -= 1
    return max(age, 0)

