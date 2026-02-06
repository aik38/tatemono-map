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


def test_building_key_stable_across_rooms():
    key_1 = ulucks_smartlink._build_building_key("東京都新宿区1-2-3", "205: フォーレスト中尾", None, None)  # noqa: SLF001
    key_2 = ulucks_smartlink._build_building_key("東京都新宿区1-2-3", "203: フォーレスト中尾", None, None)  # noqa: SLF001
    assert key_1 == key_2
