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


def test_normalize_availability_ulucks_blank_means_immediate() -> None:
    immediate, label, normalized_date = normalize_availability("", "2026-02-28", "ulucks")
    assert immediate is True
    assert label == "入居"
    assert normalized_date is None


def test_normalize_availability_ulucks_date_keeps_date_parsing() -> None:
    immediate, label, normalized_date = normalize_availability("2月26日", "2026-02-28", "ulucks")
    assert immediate is False
    assert label == "2/26"
    assert normalized_date == "2026-02-26"


def test_normalize_availability_realpro_immediate() -> None:
    immediate, label, normalized_date = normalize_availability("即入", "2026-02-28", "realpro")
    assert immediate is True
    assert label == "即入居"
    assert normalized_date is None


def test_normalize_availability_realpro_move_out_planned_keeps_raw() -> None:
    immediate, label, normalized_date = normalize_availability("退去予定", "2026-02-28", "realpro")
    assert immediate is False
    assert label == "退去予定"
    assert normalized_date is None


def test_normalize_availability_realpro_date_parses_iso() -> None:
    immediate, label, normalized_date = normalize_availability("3月6日", "2026-02-28", "realpro")
    assert immediate is False
    assert label == "3/6"
    assert normalized_date == "2026-03-06"
