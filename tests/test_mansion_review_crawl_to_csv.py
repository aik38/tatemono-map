from pathlib import Path

from scripts.mansion_review_crawl_to_csv import BASE_URL, parse_list_page, parse_max_page


def _read_fixture(name: str) -> str:
    return Path(f"tests/fixtures/mansion_review/{name}").read_text(encoding="utf-8")


def test_parse_list_page_returns_rows_for_all_fixtures() -> None:
    cases = [
        ("chintai", "1619", "chintai_1619_page1_min.html"),
        ("chintai", "1616", "chintai_1616_page1_min.html"),
        ("mansion", "1619", "mansion_1619_page1_min.html"),
        ("mansion", "1616", "mansion_1616_page1_min.html"),
    ]

    for kind, city_id, fixture in cases:
        html = _read_fixture(fixture)
        rows, _debug = parse_list_page(
            html,
            page_url=f"{BASE_URL}/{kind}/city/{city_id}.html",
            kind=kind,
            city_id=city_id,
            page_no=1,
        )

        assert len(rows) >= 1
        assert rows[0].building_name
        assert rows[0].detail_url.startswith("https://www.mansion-review.jp/")
        assert rows[0].city_page == f"{city_id}_1"


def test_parse_list_page_extracts_required_fields_and_urljoin() -> None:
    html = _read_fixture("chintai_1619_page1_min.html")
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1619.html",
        kind="chintai",
        city_id="1619",
        page_no=1,
    )

    row = rows[0]
    assert row.building_name == "サンプル小倉北レジデンス"
    assert row.detail_url == "https://www.mansion-review.jp/chintai/90011"
    assert row.address
    assert row.price_or_rent_text


def test_parse_max_page_from_fixture() -> None:
    html = _read_fixture("chintai_1619_page1_min.html")
    assert parse_max_page(html) == 55
