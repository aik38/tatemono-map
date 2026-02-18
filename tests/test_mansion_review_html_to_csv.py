from pathlib import Path

from scripts.mansion_review_html_to_csv import parse_html_file


def test_parse_city_fragment_extracts_multiple_buildings() -> None:
    rows = parse_html_file(Path("tests/fixtures/mansion_review/manual_saved_city_fragment.html"))

    names = {row.building_name for row in rows}
    assert "門司サンプルマンション" in names
    assert "ブルーハイツ門司" in names
    assert all("北九州市門司区" in row.address for row in rows)
    assert all(row.ward == "門司区" for row in rows)


def test_parse_detail_fragment_extracts_single_building() -> None:
    rows = parse_html_file(Path("tests/fixtures/mansion_review/manual_saved_detail_fragment.html"))

    names = {row.building_name for row in rows}
    assert "サンプルレジデンス" in names
    assert all("北九州市小倉北区" in row.address for row in rows)
    assert all(row.source_url == "https://www.mansion-review.jp/chintai/90001" for row in rows)
