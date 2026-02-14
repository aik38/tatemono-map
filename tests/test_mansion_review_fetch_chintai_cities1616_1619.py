from pathlib import Path

import pytest

pytest.importorskip("bs4")

from scripts.mansion_review_fetch_chintai_cities1616_1619 import city_page_url, extract_rows_from_html


def test_extract_rows_from_regex_only_city_page_with_detail_fetch() -> None:
    city_html = Path("tests/fixtures/mansion_review/chintai_city_regex_only.html").read_text(encoding="utf-8")
    detail_html = Path("tests/fixtures/mansion_review/chintai_detail_90001.html").read_text(encoding="utf-8")

    def fake_fetch(url: str) -> str:
        if url.endswith("/chintai/90001"):
            return detail_html
        raise RuntimeError(f"unexpected url {url}")

    rows, a_cnt, regex_cnt = extract_rows_from_html(
        city_html,
        city_page="https://www.mansion-review.jp/chintai/city/1616.html",
        city_id=1616,
        fetch_detail=fake_fetch,
    )

    assert a_cnt == 0
    assert regex_cnt == 1
    assert len(rows) == 1

    row = rows[0]
    assert row.detail_url.endswith("/chintai/90001")
    assert row.building_name == "サンプルレジデンス"
    assert row.room_no == "305"
    assert row.address == "福岡県北九州市小倉北区魚町1-2-3"
    assert row.layout == "1LDK"
    assert row.built == "2016年03月"


def test_city_page_url() -> None:
    assert city_page_url(1616, 1).endswith("/chintai/city/1616.html")
    assert city_page_url(1619, 2).endswith("/chintai/city/1619_2.html")
