from pathlib import Path

import pytest

pytest.importorskip("bs4")

from scripts.mansion_review_fetch_chintai_cities1616_1619 import (
    city_page_url,
    extract_building_links,
    extract_rows_from_city_html,
)


def test_extract_rows_from_city_page_table() -> None:
    city_html = Path("tests/fixtures/mansion_review/chintai_city_with_table.html").read_text(encoding="utf-8")

    rows = extract_rows_from_city_html(
        city_html,
        city_page="https://www.mansion-review.jp/chintai/city/1616.html",
        city_id=1616,
    )

    assert len(rows) == 2

    row = rows[0]
    assert row.building_name == "サンプルレジデンス"
    assert row.room_no == "305"
    assert row.address == "福岡県北九州市小倉北区魚町1-2-3"
    assert row.access == "JR鹿児島本線 小倉駅 徒歩5分"
    assert row.built == "2016年03月"
    assert row.floors == "地上12階"
    assert row.units == "48戸"
    assert row.layout == "1LDK"
    assert row.rent_man == 7.8
    assert row.fee_yen == 5000
    assert row.deposit == "1ヶ月"
    assert row.key_money == "2ヶ月"
    assert row.area_sqm == 41.2
    assert row.detail_url.endswith("/chintai/90001")


def test_extract_building_links() -> None:
    html = '<a href="/chintai/building/123">全12件を表示する</a><a href="/foo">別リンク</a>'
    links = extract_building_links(html)
    assert links == ["https://www.mansion-review.jp/chintai/building/123"]


def test_city_page_url() -> None:
    assert city_page_url(1616, 1).endswith("/chintai/city/1616.html")
    assert city_page_url(1619, 2).endswith("/chintai/city/1619_2.html")
