from pathlib import Path

import pytest

from scripts.mansion_review_fetch_mansion_cities1616_1619 import extract_rows_from_html


@pytest.mark.parametrize(
    ("fixture_name", "city_id", "city_name", "min_urls"),
    [
        ("city_1616_page1.html", 1616, "門司区", 5),
        ("city_1619_page1.html", 1619, "小倉北区", 5),
    ],
)
def test_extract_rows_from_fixture_minimum_urls(fixture_name: str, city_id: int, city_name: str, min_urls: int) -> None:
    fixture = Path("tests/fixtures/mansion_review") / fixture_name
    if not fixture.exists():
        pytest.skip(
            "TODO: tests/fixtures/mansion_review/*.html を追加後に有効化。"
            " fixture は city 固定ページの保存HTMLを想定。"
        )

    html = fixture.read_text(encoding="utf-8")
    rows, a_cnt, regex_cnt = extract_rows_from_html(
        html,
        source_url=f"https://www.mansion-review.jp/mansion/city/{city_id}.html",
        city_id=city_id,
        city_name=city_name,
    )

    assert len(rows) >= min_urls
    assert a_cnt + regex_cnt >= min_urls
