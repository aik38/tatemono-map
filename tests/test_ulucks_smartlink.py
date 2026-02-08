from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tatemono_map" / "ingest" / "ulucks_smartlink.py"
SPEC = spec_from_file_location("ulucks_smartlink_local", MODULE_PATH)
assert SPEC and SPEC.loader
ulucks_smartlink = module_from_spec(SPEC)
SPEC.loader.exec_module(ulucks_smartlink)


def test_detects_invalid_smartlink_message():
    html = """
    <html><body>
    <div class='flashMessage'>このリストは存在しません。ウラックスユーザーはログインして再表示を行ってください。</div>
    </body></html>
    """

    with pytest.raises(RuntimeError) as excinfo:
        ulucks_smartlink._validate_smartlink_html_or_raise(  # noqa: SLF001
            html, "https://example.com/list"
        )

    msg = str(excinfo.value)
    assert "smartlink が期限切れ" in msg
    assert "ブラウザで当該 URL を開いてリストが表示できるか確認" in msg
    assert "ログイン状態で smartlink を再生成" in msg


def test_fail_flag_errors_when_no_listing_upsert(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.sqlite3"

    valid_smartlink = """
    <html><body>
      <a href='https://example.com/view/smartview/abc'>detail</a>
    </body></html>
    """

    def fake_fetch(url: str) -> str:
        if "smartview" in url:
            raise ulucks_smartlink.urllib.error.URLError("network")
        return valid_smartlink

    monkeypatch.setattr(ulucks_smartlink, "_fetch_url", fake_fetch)

    with pytest.raises(RuntimeError, match="No listings were upserted"):
        ulucks_smartlink.ingest_ulucks_smartlink(
            "https://example.com/view/smartlink?link_id=abc&mail=test%40example.com",
            limit=10,
            db_path=db_path,
            fail_when_empty=True,
        )


def test_extract_listing_fields_splits_room_label_and_normalizes_name():
    html = """
    <html><head><title>205: フォーレスト中尾</title></head><body>
    <div>建物名: 205: フォーレスト中尾</div>
    <div>住所: 東京都 新宿区 1-2-3</div>
    <div>賃料: 6.5万円</div>
    <div>面積: 21.0㎡</div>
    </body></html>
    """

    extracted = ulucks_smartlink._extract_listing_fields("https://example.com/view/smartview/a", html)  # noqa: SLF001
    assert extracted["name"] == "フォーレスト中尾"
    assert extracted["room_label"] == "205"


def test_extract_listing_fields_from_th_td_and_dt_dd_pairs():
    html = """
    <html><head><title>サンプルマンション</title></head><body>
      <table>
        <tr><th>所在地</th><td>東京都 渋谷区 2-3-4</td></tr>
        <tr><th>賃料</th><td>8.2万円</td></tr>
        <tr><th>面積</th><td>30.5㎡</td></tr>
      </table>
      <dl>
        <dt>間取り</dt><dd>1LDK</dd>
        <dt>入居可能日</dt><dd>即入居可</dd>
      </dl>
    </body></html>
    """

    extracted = ulucks_smartlink._extract_listing_fields("https://example.com/view/smartview/a", html)  # noqa: SLF001
    assert extracted["address"] == "東京都 渋谷区 2-3-4"
    assert extracted["rent_yen"] == 82000
    assert extracted["area_sqm"] == 30.5
    assert extracted["layout"] == "1LDK"
    assert extracted["move_in"] == "即入居可"


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        (
            "smartview_th_td.html",
            {
                "address": "福岡県 福岡市中央区 1-2-3",
                "rent_yen": 65000,
                "area_sqm": 25.1,
                "layout": "1K",
                "move_in": "即入居可",
                "maint_yen": 5000,
            },
        ),
        (
            "smartview_dt_dd.html",
            {
                "address": "福岡県福岡市博多区4-5-6",
                "rent_yen": 65000,
                "area_sqm": 30.2,
                "layout": "2DK",
                "move_in": "2026年03月下旬",
                "maint_yen": 0,
            },
        ),
    ],
)
def test_extract_listing_fields_from_smartview_fixtures(fixture_name: str, expected: dict[str, object]):
    fixture = Path(__file__).resolve().parent / "fixtures" / fixture_name
    html = fixture.read_text(encoding="utf-8")

    extracted = ulucks_smartlink._extract_listing_fields("https://example.com/view/smartview/a", html)  # noqa: SLF001

    assert extracted["address"] == expected["address"]
    assert extracted["rent_yen"] == expected["rent_yen"]
    assert extracted["area_sqm"] == expected["area_sqm"]
    assert extracted["layout"] == expected["layout"]
    assert extracted["move_in"] == expected["move_in"]
    assert extracted["maint_yen"] == expected["maint_yen"]


def test_extract_listings_from_smartlink_page_fixture():
    fixture = Path(__file__).resolve().parent / "fixtures" / "smartlink_listing_snippet.html"
    html = fixture.read_text(encoding="utf-8")

    extracted = ulucks_smartlink._extract_listings_from_smartlink_page(  # noqa: SLF001
        "https://example.com/view/smartlink?link_id=abc&mail=test%40example.com",
        html,
    )

    detail_url = "https://example.com/view/smartview/abc123"
    assert detail_url in extracted
    row = extracted[detail_url]
    assert row["rent_yen"] == 55000
    assert row["maint_yen"] == 4000
    assert row["area_sqm"] == 50.0
    assert row["layout"] == "2LDK"
    assert row["address"] == "福岡県北九州市小倉北区1-2-3"


def test_extract_listings_from_smartlink_page_prefers_container_row_fixture():
    fixture = Path(__file__).resolve().parent / "fixtures" / "smartlink_listing_table.html"
    html = fixture.read_text(encoding="utf-8")

    extracted = ulucks_smartlink._extract_listings_from_smartlink_page(  # noqa: SLF001
        "https://example.com/view/smartlink?link_id=abc&mail=test%40example.com",
        html,
    )

    detail_url = "https://example.com/view/smartview/xyz001"
    assert detail_url in extracted
    row = extracted[detail_url]
    assert row["rent_yen"] == 58000
    assert row["maint_yen"] == 2000
    assert row["area_sqm"] == 34.5
    assert row["layout"] == "1LDK"
    assert row["address"] == "福岡県北九州市小倉北区浅野1-2-3"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5.5万", 55000),
        ("5.1万", 51000),
        ("0.4万", 4000),
        ("0万", 0),
        ("—", None),
    ],
)
def test_parse_money_man_unit(value: str, expected: int | None):
    assert ulucks_smartlink._parse_money(value) == expected  # noqa: SLF001


def test_ingest_smartlink_uses_listing_hints_when_detail_missing_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.sqlite3"
    source_url = "https://example.com/view/smartlink?link_id=abc&mail=test%40example.com"
    list_html = (Path(__file__).resolve().parent / "fixtures" / "smartlink_listing_table.html").read_text(encoding="utf-8")
    detail_html = """
    <html><head><title>サンプル物件</title></head><body>
      <div>建物名: サンプル物件</div>
    </body></html>
    """

    def fake_fetch(url: str) -> str:
        if "smartview" in url:
            return detail_html
        return list_html

    monkeypatch.setattr(ulucks_smartlink, "_fetch_url", fake_fetch)

    ulucks_smartlink.ingest_ulucks_smartlink(
        source_url,
        limit=10,
        db_path=db_path,
    )

    conn = ulucks_smartlink.sqlite3.connect(str(db_path))
    conn.row_factory = ulucks_smartlink.sqlite3.Row
    try:
        row = conn.execute("SELECT rent_yen, area_sqm, layout, address FROM listings").fetchone()
        assert row is not None
        assert row["rent_yen"] == 58000
        assert row["area_sqm"] == 34.5
        assert row["layout"] == "1LDK"
        assert row["address"] == "福岡県北九州市小倉北区浅野1-2-3"

        summary = conn.execute(
            "SELECT address, rent_min, rent_max, area_min, area_max, layout_types_json FROM building_summaries"
        ).fetchone()
        assert summary is not None
        assert summary["address"] == "福岡県北九州市小倉北区浅野1-2-3"
        assert summary["rent_min"] == 58000
        assert summary["rent_max"] == 58000
        assert summary["area_min"] == 34.5
        assert summary["area_max"] == 34.5
        assert "1LDK" in summary["layout_types_json"]
    finally:
        conn.close()


def test_upsert_listing_does_not_overwrite_existing_values_with_empty_or_null(tmp_path: Path):
    db_path = tmp_path / "listings.sqlite3"
    conn = ulucks_smartlink.sqlite3.connect(str(db_path))
    try:
        ulucks_smartlink._ensure_tables(conn)  # noqa: SLF001
        conn.row_factory = ulucks_smartlink.sqlite3.Row

        ulucks_smartlink._upsert_listing(  # noqa: SLF001
            conn,
            {
                "listing_key": "key-1",
                "building_key": "building-1",
                "name": "テストマンション",
                "room_label": "101",
                "address": "東京都新宿区1-2-3",
                "rent_yen": 70000,
                "maint_yen": 5000,
                "fee_yen": 5000,
                "area_sqm": 25.1,
                "layout": "1K",
                "move_in": "即入居可",
                "lat": 35.0,
                "lon": 139.0,
                "source_url": "https://example.com/1",
                "fetched_at": "2026-01-01T00:00:00+00:00",
            },
        )

        ulucks_smartlink._upsert_listing(  # noqa: SLF001
            conn,
            {
                "listing_key": "key-1",
                "building_key": "",
                "name": "",
                "room_label": "",
                "address": "",
                "rent_yen": None,
                "maint_yen": None,
                "fee_yen": None,
                "area_sqm": None,
                "layout": "",
                "move_in": "",
                "lat": None,
                "lon": None,
                "source_url": "",
                "fetched_at": "2026-01-02T00:00:00+00:00",
            },
        )

        row = conn.execute("SELECT * FROM listings WHERE listing_key = 'key-1'").fetchone()
        assert row is not None
        assert row["building_key"] == "building-1"
        assert row["name"] == "テストマンション"
        assert row["room_label"] == "101"
        assert row["address"] == "東京都新宿区1-2-3"
        assert row["rent_yen"] == 70000
        assert row["maint_yen"] == 5000
        assert row["area_sqm"] == 25.1
        assert row["layout"] == "1K"
        assert row["move_in"] == "即入居可"
        assert row["lat"] == 35.0
        assert row["lon"] == 139.0
        assert row["source_url"] == "https://example.com/1"
    finally:
        conn.close()


def test_building_key_stable_across_rooms():
    key_1 = ulucks_smartlink._build_building_key("東京都新宿区1-2-3", "205: フォーレスト中尾", None, None)  # noqa: SLF001
    key_2 = ulucks_smartlink._build_building_key("東京都新宿区1-2-3", "203: フォーレスト中尾", None, None)  # noqa: SLF001
    assert key_1 == key_2


def test_ingest_smartlink_follows_pagination_and_respects_max_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.sqlite3"
    source_url = "https://example.com/view/smartlink?link_id=abc&mail=test%40example.com&sort=desc"
    list_1 = """
    <html><body>
      <a href='https://example.com/view/smartview/1'>d1</a>
      <a href='https://example.com/view/smartview/2'>d2</a>
      <a rel='next' href='/view/smartlink/page:2/'>next</a>
    </body></html>
    """
    list_2 = """
    <html><body>
      <a href='https://example.com/view/smartview/3'>d3</a>
      <a href='https://example.com/view/smartview/4'>d4</a>
    </body></html>
    """
    detail = """
    <html><head><title>101: テストマンション</title></head><body>
      <div>建物名: 101: テストマンション</div>
      <div>住所: 東京都新宿区1-2-3</div>
      <div>賃料: 5.2万円</div>
      <div>面積: 20.1㎡</div>
    </body></html>
    """

    requested_urls: list[str] = []

    def fake_fetch(url: str) -> str:
        requested_urls.append(url)
        if url in {source_url, "https://example.com/view/smartlink/?link_id=abc&mail=test%40example.com&sort=desc"}:
            return list_1
        if url == "https://example.com/view/smartlink/page:2/?link_id=abc&mail=test%40example.com&sort=desc":
            return list_2
        if "smartview" in url:
            return detail
        raise AssertionError(url)

    monkeypatch.setattr(ulucks_smartlink, "_fetch_url", fake_fetch)

    ulucks_smartlink.ingest_ulucks_smartlink(
        source_url,
        limit=3,
        db_path=db_path,
        fail_when_empty=True,
    )

    conn = ulucks_smartlink.sqlite3.connect(str(db_path))
    try:
        listing_count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        assert listing_count == 3
    finally:
        conn.close()

    assert "https://example.com/view/smartlink/page:2/?link_id=abc&mail=test%40example.com&sort=desc" in requested_urls


def test_normalize_smartlink_url_accepts_paged_url_and_normalizes_mail():
    url = "https://kitakyushu.ulucks.jp/view/smartlink/page:3/sort:Rent.modified/direction:desc?link_id=xTkB8Pl1&mail=u5.inc.orporated.info@gmail.com&sort=1"
    normalized = ulucks_smartlink._normalize_smartlink_url(url)  # noqa: SLF001
    assert "/page:" not in normalized
    assert "link_id=xTkB8Pl1" in normalized
    assert "mail=u5.inc.orporated.info%40gmail.com" in normalized


def test_ingest_smartlink_crawls_all_pages_from_paged_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.sqlite3"
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    list_1 = (fixture_dir / "smartlink_page_1.html").read_text(encoding="utf-8")
    list_2 = (fixture_dir / "smartlink_page_2.html").read_text(encoding="utf-8")
    list_3 = (fixture_dir / "smartlink_page_3.html").read_text(encoding="utf-8")

    source_url = "https://example.com/view/smartlink/page:2/sort:Rent.modified/direction:desc?link_id=abc&mail=test@example.com"

    detail = """
    <html><head><title>101: テストマンション</title></head><body>
      <div>建物名: 101: テストマンション</div>
      <div>住所: 東京都新宿区1-2-3</div>
      <div>賃料: 5.2万円</div>
      <div>面積: 20.1㎡</div>
      <div>間取り: 1K</div>
      <div>入居可能日: 即入居可</div>
    </body></html>
    """

    def fake_fetch(url: str) -> str:
        if "/page:2/" in url:
            return list_2
        if "/page:3/" in url:
            return list_3
        if "smartlink" in url:
            return list_1
        if "smartview" in url:
            return detail
        raise AssertionError(url)

    monkeypatch.setattr(ulucks_smartlink, "_fetch_url", fake_fetch)

    ulucks_smartlink.ingest_ulucks_smartlink(
        source_url,
        limit=None,
        db_path=db_path,
        fail_when_empty=True,
    )

    conn = ulucks_smartlink.sqlite3.connect(str(db_path))
    try:
        listing_count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        assert listing_count == 5
    finally:
        conn.close()
