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
            "https://example.com/list",
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
        if url == source_url:
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
