from pathlib import Path

import pytest

pytest.importorskip("bs4")

from scripts.mansion_review_fetch_chintai_cities1616_1619 import city_page_url, extract_rows_from_html


@pytest.mark.parametrize(
    ("fixture_name", "city_id", "min_urls"),
    [
        ("chintai_city_1616_page1.html", 1616, 5),
        ("chintai_city_1619_page1.html", 1619, 5),
    ],
)
def test_extract_rows_from_fixture_minimum_urls(fixture_name: str, city_id: int, min_urls: int) -> None:
    fixture = Path("tests/fixtures/mansion_review") / fixture_name
    if not fixture.exists():
        pytest.skip(
            "TODO: tests/fixtures/mansion_review/chintai_city_*.html を追加後に有効化。"
            " fixture は /chintai/city 固定ページの保存HTMLを想定。"
        )

    html = fixture.read_text(encoding="utf-8")
    rows, a_cnt, regex_cnt = extract_rows_from_html(
        html,
        city_page=f"https://www.mansion-review.jp/chintai/city/{city_id}.html",
        city_id=city_id,
    )

    assert len(rows) >= min_urls
    assert a_cnt + regex_cnt >= min_urls


def test_city_page_url() -> None:
    assert city_page_url(1616, 1).endswith("/chintai/city/1616.html")
    assert city_page_url(1619, 2).endswith("/chintai/city/1619_2.html")
