from datetime import date

from tatemono_map.util.building_age import age_years_from_built_year_month


def test_age_years_from_built_year_month() -> None:
    assert age_years_from_built_year_month("2001-05", as_of=date(2026, 3, 1)) == 24
    assert age_years_from_built_year_month("1989-04", as_of=date(2026, 3, 1)) == 36
    assert age_years_from_built_year_month("2025-01", as_of=date(2026, 3, 1)) == 1
    assert age_years_from_built_year_month("2026-03", as_of=date(2026, 3, 1)) == 0
    assert age_years_from_built_year_month("2026-04", as_of=date(2026, 3, 1)) == 0


def test_age_years_from_built_year_month_invalid() -> None:
    assert age_years_from_built_year_month(None) is None
    assert age_years_from_built_year_month("") is None
    assert age_years_from_built_year_month("2025-13") is None
