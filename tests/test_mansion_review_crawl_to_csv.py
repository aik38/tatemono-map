import importlib.util
from pathlib import Path
import sys

import pytest

from tests.conftest import repo_path

MODULE_PATH = repo_path("scripts", "mansion_review_crawl_to_csv.py")
if not MODULE_PATH.exists():
    pytest.skip("mansion-review scripts are optional and not present", allow_module_level=True)
SPEC = importlib.util.spec_from_file_location("mansion_review_crawl_to_csv", MODULE_PATH)
assert SPEC and SPEC.loader
crawl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = crawl
SPEC.loader.exec_module(crawl)
BASE_URL = crawl.BASE_URL
parse_list_page = crawl.parse_list_page
parse_max_page = crawl.parse_max_page


def _read_fixture(name: str) -> str:
    return repo_path("tests", "fixtures", "mansion_review", name).read_text(encoding="utf-8")


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
    assert parse_max_page(html, kind="chintai", city_id="1619") == 55


@pytest.mark.parametrize(
    ("fixture", "kind", "city_id", "expected"),
    [
        ("chintai_city_pages_7.html", "chintai", "1619", 7),
        ("mansion_city_pages_14.html", "mansion", "1616", 14),
        ("chintai_city_pages_12.html", "chintai", "1616", 12),
        ("mansion_city_pages_52.html", "mansion", "1619", 52),
    ],
)
def test_parse_max_page_uses_city_pagination_links_only(
    fixture: str,
    kind: str,
    city_id: str,
    expected: int,
) -> None:
    html = _read_fixture(fixture)
    assert parse_max_page(html, kind=kind, city_id=city_id) == expected


def test_parse_max_page_ignores_empty_href_and_href_without_value() -> None:
    html = """
    <html><body>
      <ul class="pagination">
        <li><a href>Prev</a></li>
        <li><a href="">1</a></li>
        <li><a href="/chintai/city/1619_3.html">3</a></li>
      </ul>
    </body></html>
    """
    assert parse_max_page(html, kind="chintai", city_id="1619") == 3


def test_parse_max_page_without_pagination_returns_one() -> None:
    html = "<html><body><div>no pagination</div></body></html>"
    assert parse_max_page(html, kind="chintai", city_id="1619") == 1


def test_run_crawl_with_fixed_max_pages_skips_parse_max_page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_parse_max_page(_html: str, _kind: str, _city_id: str) -> int:
        calls.append("called")
        raise AssertionError("parse_max_page must not be called when max_pages > 0")

    class FakeSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    def fake_fetch_html(*_args, **_kwargs):
        return (
            """
            <html><body>
              <section class="property-card">
                <h2>dummy</h2><a href="/chintai/1">detail</a><dd class="address">addr</dd>
              </section>
            </body></html>
            """,
            False,
        )

    monkeypatch.setattr(crawl, "parse_max_page", fake_parse_max_page)
    monkeypatch.setattr(crawl.requests, "Session", FakeSession)
    monkeypatch.setattr(crawl, "fetch_html", fake_fetch_html)

    _out_dir, _csv, stats = crawl.run_crawl(
        city_ids=["1619"],
        kinds=["chintai"],
        mode="list",
        out_root=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        sleep_sec=0,
        max_pages=1,
        retry_count=0,
        user_agent="ua",
    )

    assert calls == []
    assert stats["pages_total"] == 1


def test_run_crawl_auto_mode_falls_back_to_next_and_stops_on_same_detail_urls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    page1 = """
    <html><body>
      <nav class="pagination"><a rel="next" href="/chintai/city/1619_2.html">次へ</a></nav>
      <section class="property-card"><h2>A</h2><a href="/chintai/1">detail</a><dd class="address">addr</dd></section>
    </body></html>
    """
    page2 = """
    <html><body>
      <nav class="pagination"><a rel="next" href="/chintai/city/1619_3.html">次へ</a></nav>
      <section class="property-card"><h2>A</h2><a href="/chintai/1">detail</a><dd class="address">addr</dd></section>
    </body></html>
    """
    fetched_urls: list[str] = []

    def fake_fetch_html(_session, url: str, *_args, **_kwargs):
        fetched_urls.append(url)
        if url.endswith("/chintai/city/1619.html"):
            return page1, False
        if url.endswith("/chintai/city/1619_2.html"):
            return page2, False
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(crawl.requests, "Session", FakeSession)
    monkeypatch.setattr(crawl, "fetch_html", fake_fetch_html)

    _out_dir, _csv, stats = crawl.run_crawl(
        city_ids=["1619"],
        kinds=["chintai"],
        mode="list",
        out_root=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        sleep_sec=0,
        max_pages=0,
        retry_count=0,
        user_agent="ua",
        auto_max_threshold=1,
    )

    assert fetched_urls == [
        "https://www.mansion-review.jp/chintai/city/1619.html",
        "https://www.mansion-review.jp/chintai/city/1619_2.html",
    ]
    assert stats["pages_total"] == 2
    assert stats["rows_total"] == 2
    assert stats["autopage"][0]["mode"] == "follow_next"


def test_run_crawl_records_actual_page_url_for_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    page1 = """
    <html><body>
      <nav class="pagination">
        <a href="/chintai/city/1619.html">1</a><a href="/chintai/city/1619_2.html">2</a>
      </nav>
      <section class="property-card"><h2>P1</h2><a href="/chintai/1">detail</a><dd class="address">addr</dd></section>
    </body></html>
    """
    page2 = """
    <html><body>
      <section class="property-card"><h2>P2</h2><a href="/chintai/2">detail</a><dd class="address">addr2</dd></section>
    </body></html>
    """
    fetch_map = {
        "https://www.mansion-review.jp/chintai/city/1619.html": page1,
        "https://www.mansion-review.jp/chintai/city/1619_2.html": page2,
    }

    def fake_fetch_html(_session, url: str, *_args, **_kwargs):
        return fetch_map[url], False

    captured_rows: list[crawl.ListRow] = []

    def fake_write_csv(rows, _out_csv):
        captured_rows.extend(rows)

    monkeypatch.setattr(crawl.requests, "Session", FakeSession)
    monkeypatch.setattr(crawl, "fetch_html", fake_fetch_html)
    monkeypatch.setattr(crawl, "write_csv", fake_write_csv)

    crawl.run_crawl(
        city_ids=["1619"],
        kinds=["chintai"],
        mode="list",
        out_root=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        sleep_sec=0,
        max_pages=0,
        retry_count=0,
        user_agent="ua",
    )

    assert [row.page_url for row in captured_rows] == [
        "https://www.mansion-review.jp/chintai/city/1619.html",
        "https://www.mansion-review.jp/chintai/city/1619_2.html",
    ]
