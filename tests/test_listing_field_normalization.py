from tatemono_map.normalize.listing_fields import normalize_availability, normalize_built


def test_normalize_built_extracts_year_month_and_age() -> None:
    ym, age = normalize_built("2023年1月 (3年)")
    assert ym == "2023-01"
    assert age == 3


def test_normalize_availability_immediate() -> None:
    immediate, label, normalized_date = normalize_availability("即入可", "2026-02-28")
    assert immediate is True
    assert label == "即入居"
    assert normalized_date is None


def test_normalize_availability_complements_year_with_rollover() -> None:
    immediate, label, normalized_date = normalize_availability("1月5日", "2026-12-28")
    assert immediate is False
    assert label == "1/5"
    assert normalized_date == "2027-01-05"


def test_normalize_availability_immediate_short_token() -> None:
    immediate, label, normalized_date = normalize_availability("即", "2026-02-28")
    assert immediate is True
    assert label == "即入居"
    assert normalized_date is None


def test_normalize_availability_without_reference_date_keeps_raw_only() -> None:
    immediate, label, normalized_date = normalize_availability("2月28日", None)
    assert immediate is False
    assert label == "2月28日"
    assert normalized_date is None
