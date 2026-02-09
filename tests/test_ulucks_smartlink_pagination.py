from pathlib import Path

import pytest

from tatemono_map.ingest.ulucks_smartlink import extract_pagination_hrefs, run


class DummyResponse:
    def __init__(self, text: str):
        self.text = text
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None


def test_extract_pagination_hrefs_contains_page2():
    seed = "https://kitakyushu.ulucks.jp/view/smartlink/?link_id=NCuN0Jmw&mail=u5.inc.orporated.info%40gmail.com"
    page1_html = """
    <html><body>
      <div class="pagination">
        <a href="/view/smartlink/page:2/sort:Rent.modified/direction:desc?link_id=NCuN0Jmw&sort=1&mail=u5.inc.orporated.info@gmail.com">2</a>
      </div>
    </body></html>
    """
    hrefs = extract_pagination_hrefs(seed, page1_html)
    assert any("page:2" in href for href in hrefs)


def test_href_is_followed_as_is_without_rebuilding(monkeypatch, tmp_path):
    seed = "https://kitakyushu.ulucks.jp/view/smartlink/?link_id=NCuN0Jmw&mail=u5.inc.orporated.info%40gmail.com"
    page2 = "https://kitakyushu.ulucks.jp/view/smartlink/page:2/sort:Rent.modified/direction:desc?link_id=NCuN0Jmw&sort=1&mail=u5.inc.orporated.info@gmail.com"
    page37 = "https://kitakyushu.ulucks.jp/view/smartlink/page:37/sort:Rent.modified/direction:desc?link_id=NCuN0Jmw&sort=1&mail=u5.inc.orporated.info@gmail.com"

    pages = {
        seed: f'<a href="{page2}">2</a>',
        page2: f'<a href="{page37}">37</a>',
        page37: "<div>last</div>",
    }
    called: list[str] = []

    def fake_get(url, timeout, headers):
        called.append(url)
        return DummyResponse(pages[url])

    monkeypatch.setattr("tatemono_map.ingest.ulucks_smartlink.requests.get", fake_get)
    saved = run(seed, str(tmp_path / "db.sqlite3"), max_items=10)

    assert saved == 3
    assert called == [seed, page2, page37]


def test_error_marker_raises_hard_error(monkeypatch, tmp_path):
    seed = "https://kitakyushu.ulucks.jp/view/smartlink/?link_id=abc&mail=user%40example.com"

    def fake_get(url, timeout, headers):
        return DummyResponse("<html><body>このリストは存在しません</body></html>")

    monkeypatch.setattr("tatemono_map.ingest.ulucks_smartlink.requests.get", fake_get)
    monkeypatch.setattr(
        "tatemono_map.ingest.ulucks_smartlink.fetch_pages_with_playwright",
        lambda _url, max_pages=200: [(seed, "<html><body>このリストは存在しません</body></html>")],
    )

    with pytest.raises(RuntimeError, match="error page marker"):
        run(seed, str(tmp_path / "db.sqlite3"), max_items=1)


def test_no_url_normalization_functions_used_for_smartlink():
    forbidden = ("urlparse", "parse_qs", "urlencode", "urlunparse", "quote(", "unquote(")
    targets = [
        Path("src/tatemono_map/ingest/ulucks_smartlink.py"),
        Path("src/tatemono_map/ingest/ulucks_playwright.py"),
    ]
    for target in targets:
        text = target.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token} should not be used in {target}"
