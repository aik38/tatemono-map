from pathlib import Path

from tatemono_map.ingest.smartlink_dom import extract_records
from tatemono_map.ingest.ulucks_playwright import _extract_pagination_hrefs


def test_extract_records_from_debug_fixture_returns_records():
    html = Path("tests/fixtures/ulucks/smartlink_page1_before_parse.html").read_text(encoding="utf-8")

    records = extract_records(
        "https://kitakyushu.ulucks.jp/view/smartlink/?link_id=NCuN0Jmw&mail=user%40example.com",
        html,
    )

    assert len(records) >= 1
    first = records[0]
    assert first.name
    assert first.address
    assert first.rent_yen is not None
    assert first.area_sqm is not None
    assert first.updated_at


def test_extract_pagination_hrefs_from_debug_fixture_contains_page2_and_page3():
    html = Path("tests/fixtures/ulucks/smartlink_page1_before_parse.html").read_text(encoding="utf-8")
    source_url = "https://kitakyushu.ulucks.jp/view/smartlink/?link_id=NCuN0Jmw&mail=user%40example.com"

    hrefs = _extract_pagination_hrefs(source_url, html)

    assert any("/view/smartlink/page:2/" in href for href in hrefs)
    assert any("/view/smartlink/page:3/" in href for href in hrefs)
    assert all(href.startswith("https://kitakyushu.ulucks.jp/") for href in hrefs)
