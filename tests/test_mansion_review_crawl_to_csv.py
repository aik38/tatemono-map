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


def test_parse_list_page_rejects_polluted_layout_text() -> None:
    html = """
    <html><body>
      <section class="property-card">
        <h2 class="property-name">汚染テストマンション</h2>
        <p class="address">福岡県北九州市小倉北区魚町1-2-3</p>
        <table>
          <thead><tr><th>賃料(管理費)</th><th>敷金</th><th>礼金</th><th>専有面積</th><th>間取り</th><th>詳細</th></tr></thead>
          <tbody>
            <tr>
              <td>8.2万円(4,000円)</td><td>1ヶ月</td><td>1ヶ月</td><td>40.0㎡</td>
              <td>住所・交通・築年数・総戸数・賃料表・号室・全 件を表示する・function()</td>
              <td><a href="/chintai/90099">詳細</a></td>
            </tr>
          </tbody>
        </table>
      </section>
    </body></html>
    """
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1619.html",
        kind="chintai",
        city_id="1619",
        page_no=1,
    )
    assert len(rows) == 1
    assert rows[0].layout_text == ""
    assert rows[0].detail_url == "https://www.mansion-review.jp/chintai/90099"
    assert rows[0].fee_text == "4,000円"
    assert rows[0].deposit_text == "1ヶ月"
    assert rows[0].key_money_text == "1ヶ月"


def test_parse_max_page_from_fixture() -> None:
    html = _read_fixture("chintai_1619_page1_min.html")
    assert parse_max_page(html, kind="chintai", city_id="1619") == 55


def test_parse_list_page_handles_chintai_table_without_room_td_shift() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>門司テストレジデンス</h3>
        <dl><dt>交通</dt><dd>JR門司駅 徒歩8分</dd><dt>築年数</dt><dd>築16年</dd><dt>階建て</dt><dd>10階建て</dd><dt>総戸数</dt><dd>45戸</dd></dl>
        <table class="recommendTable">
          <thead>
            <tr><th>号室</th><th>賃料(管理費)</th><th>敷金</th><th>礼金</th><th>専有面積</th><th>間取り</th><th>所在階</th><th>向き</th></tr>
          </thead>
          <tbody class="recommend_row">
            <tr><td>7.8万円(5,000円)</td><td>1ヶ月</td><td>2ヶ月</td><td>41.2㎡</td><td>1LDK</td><td>3階</td><td>南</td></tr>
          </tbody>
        </table>
        <a href="/chintai/91001">詳細</a>
      </li>
    </body></html>
    """
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        kind="chintai",
        city_id="1616",
        page_no=1,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.price_or_rent_text == "7.8万円"
    assert row.deposit_text == "1ヶ月"
    assert row.key_money_text == "2ヶ月"
    assert row.area_text == "41.2㎡"
    assert row.direction_text == "南"
    assert row.access_text == "JR門司駅 徒歩8分"
    assert row.built_text == "築16年"
    assert row.building_floor_count_text == "10階建て"
    assert row.total_units_text == "45戸"


def test_parse_list_page_extracts_chintai_fee_deposit_key_money_from_individual_columns() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>門司ラベル別テスト</h3>
        <dl>
          <dt>交通</dt><dd>JR門司駅 徒歩6分</dd>
          <dt>築年月</dt><dd>築9年</dd>
          <dt>階建て</dt><dd>14階建て</dd>
          <dt>総戸数</dt><dd>80戸</dd>
        </dl>
        <table class="recommendTable">
          <thead>
            <tr><th>賃料</th><th>管理費</th><th>敷金</th><th>礼金</th><th>専有面積</th><th>間取り</th></tr>
          </thead>
          <tbody class="recommend_row">
            <tr><td>8.8万円</td><td>6,000円</td><td>1ヶ月</td><td>なし</td><td>42.5㎡</td><td>1LDK</td></tr>
          </tbody>
        </table>
        <a href="/chintai/91999">詳細</a>
      </li>
    </body></html>
    """
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        kind="chintai",
        city_id="1616",
        page_no=1,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.fee_text == "6,000円"
    assert row.deposit_text == "1ヶ月"
    assert row.key_money_text == "なし"
    assert row.access_text == "JR門司駅 徒歩6分"
    assert row.built_text == "築9年"
    assert row.building_floor_count_text == "14階建て"
    assert row.total_units_text == "80戸"


def test_parse_list_page_uses_recommend_table_rent_not_property_summary() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>小倉北サマリー混在テスト</h3>
        <div class="property-detail-content_main">
          <dl>
            <dt>住所</dt><dd>福岡県北九州市小倉北区魚町2-2-2</dd>
            <dt>交通</dt><dd>JR小倉駅 徒歩7分</dd>
            <dt>築年数</dt><dd>築11年</dd>
            <dt>階建て</dt><dd>15階建て</dd>
            <dt>総戸数</dt><dd>100戸</dd>
          </dl>
        </div>
        <div class="property-detail-content_sub">
          <p class="price">平均賃料 13.8086万円</p>
          <p>坪賃料 0.9万円</p>
          <p>口コミ数 12件</p>
          <p>アクセス数 1300</p>
        </div>
        <table class="recommendTable">
          <thead>
            <tr><th>賃料(管理費)</th><th>敷金</th><th>礼金</th><th>専有面積</th><th>間取り</th><th>所在階</th><th>向き</th></tr>
          </thead>
          <tbody class="recommend_row">
            <tr><td>8.6万円(6,000円)</td><td>1ヶ月</td><td>1ヶ月</td><td>40.5㎡</td><td>1LDK</td><td>4階</td><td>南</td></tr>
          </tbody>
        </table>
        <a href="/chintai/92001">詳細</a>
      </li>
    </body></html>
    """
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1619.html",
        kind="chintai",
        city_id="1619",
        page_no=1,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.price_or_rent_text == "8.6万円"
    assert row.fee_text == "6,000円"
    assert row.deposit_text == "1ヶ月"
    assert row.key_money_text == "1ヶ月"
    assert row.access_text == "JR小倉駅 徒歩7分"
    assert row.built_text == "築11年"
    assert row.building_floor_count_text == "15階建て"
    assert row.total_units_text == "100戸"


def test_parse_list_page_chintai_ignores_summary_price_when_recommend_exists_and_parses_slash_fee() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>リファレンス門司駅前</h3>
        <div class="property-detail-content_sub">
          <p class="price">45,619円</p>
        </div>
        <table class="recommendTable">
          <thead>
            <tr>
              <th colspan="3" class="size_title">このマンションの【賃貸】物件情報</th>
              <th class="size2">賃料(管理費)</th><th class="size2">敷金</th><th class="size2">礼金</th>
              <th class="size2">専有面積</th><th class="size2">間取り</th><th class="size1">所在階</th><th class="size1">向き</th>
            </tr>
          </thead>
          <tbody class="recommend_row">
            <tr>
              <td><img src="/img/common/floorplan-preparing-list.png"></td>
              <td><a href="/chintai/132825003/7083.html">リファレンス門司駅前</a></td>
              <td>4.6万円/3,000円</td><td>無</td><td>無</td><td>27.9㎡</td><td>1K</td><td>1階</td><td>西</td>
            </tr>
          </tbody>
        </table>
      </li>
    </body></html>
    """
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        kind="chintai",
        city_id="1616",
        page_no=1,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.price_or_rent_text == "4.6万円"
    assert row.fee_text == "3,000円"
    assert row.deposit_text == "無"
    assert row.key_money_text == "無"
    assert row.area_text == "27.9㎡"
    assert row.layout_text == "1K"
    assert row.floor_text == "1階"
    assert row.direction_text == "西"


def test_parse_list_page_chintai_parses_bracket_fee_from_recommend_row_fixed_td_positions() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>リファレンス門司駅前</h3>
        <div class="property-detail-content_sub">
          <p class="price">45,654円</p>
        </div>
        <table class="recommendTable">
          <tbody class="recommend_row">
            <tr>
              <td><img src="/img/common/floorplan-preparing-list.png"></td>
              <td><a href="/chintai/132825003/7083.html">リファレンス門司駅前</a></td>
              <td>4.6万円<br>(3,000円)</td><td>無</td><td>無</td><td>27.9㎡</td><td>1K</td><td>1階</td><td>西</td>
              <td class="recommend_update_row">情報取得日:2026年03月22日</td>
            </tr>
          </tbody>
        </table>
      </li>
    </body></html>
    """
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        kind="chintai",
        city_id="1616",
        page_no=1,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.price_or_rent_text == "4.6万円"
    assert row.fee_text == "3,000円"
    assert row.deposit_text == "無"
    assert row.key_money_text == "無"
    assert row.area_text == "27.9㎡"
    assert row.layout_text == "1K"
    assert row.floor_text == "1階"
    assert row.direction_text == "西"


def test_parse_list_page_chintai_does_not_fallback_to_summary_when_recommend_row_missing_rent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>賃料欠損テスト</h3>
        <div class="property-detail-content_sub">
          <p class="price">45,654円</p>
        </div>
        <table class="recommendTable">
          <tbody class="recommend_row">
            <tr>
              <td><img src="/img/common/floorplan-preparing-list.png"></td>
              <td><a href="/chintai/132825003/7083.html">賃料欠損テスト</a></td>
              <td>-</td><td>無</td><td>無</td><td>27.9㎡</td><td>1K</td><td>1階</td><td>西</td>
            </tr>
          </tbody>
        </table>
      </li>
    </body></html>
    """
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        kind="chintai",
        city_id="1616",
        page_no=1,
    )
    captured = capsys.readouterr()

    assert len(rows) == 1
    row = rows[0]
    assert row.price_or_rent_text == ""
    assert row.fee_text == ""
    assert "[WARN] chintai recommend_row detected but rent not parsed:" in captured.out


def test_parse_list_page_drops_polluted_direction_text() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>門司分譲テスト</h3>
        <table class="recommendTable">
          <thead>
            <tr><th>価格</th><th>管理費</th><th>修繕積立金</th><th>間取り</th><th>専有面積</th><th>所在階</th><th>向き</th></tr>
          </thead>
          <tbody class="recommend_row">
            <tr><td>2,480万円</td><td>8,000円</td><td>4,500円</td><td>2LDK</td><td>63.0㎡</td><td>10階</td><td>価格評価</td></tr>
          </tbody>
        </table>
        <a href="/mansion/81001">詳細</a>
      </li>
    </body></html>
    """
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1616.html",
        kind="mansion",
        city_id="1616",
        page_no=1,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.price_or_rent_text == "2,480万円"
    assert row.fee_text == ""
    assert row.repair_fund_text == ""
    assert row.floor_text == "10階"
    assert row.direction_text == ""


def test_parse_list_page_handles_mansion_table_without_room_td_shift() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>小倉北分譲テスト</h3>
        <table class="recommendTable">
          <thead>
            <tr><th>号室</th><th>価格</th><th>坪単価</th><th>専有面積</th><th>間取り</th><th>所在階</th><th>向き</th><th>価格評価</th></tr>
          </thead>
          <tbody class="recommend_row">
            <tr><td>2,980万円</td><td>150万円</td><td>65.4㎡</td><td>3LDK</td><td>12階</td><td>南東</td><td>普通</td></tr>
          </tbody>
        </table>
        <a href="/mansion/81002">詳細</a>
      </li>
    </body></html>
    """
    rows, _debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1619.html",
        kind="mansion",
        city_id="1619",
        page_no=1,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.price_or_rent_text == "2,980万円"
    assert row.area_text == "65.4㎡"
    assert row.layout_text == "3LDK"
    assert row.floor_text == "12階"
    assert row.direction_text == "南東"


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


def test_parse_detail_facts_extracts_structure_age_and_availability() -> None:
    html = _read_fixture("chintai_detail_facts_min.html")
    row = crawl.parse_detail_facts(
        html,
        detail_url="https://www.mansion-review.jp/chintai/99999",
        fallback_name="fallback",
        fallback_address="fallback address",
    )

    assert row.building_name == "サンプル小倉北レジデンス"
    assert row.address.startswith("北九州市小倉北区")
    assert row.structure == "RC"
    assert row.availability_label == "即入居"


def test_run_crawl_facts_writes_combined_facts_csv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    list_page = """
    <html><body>
      <section class="property-card"><h2>A</h2><a href="/chintai/1">detail</a><dd class="address">福岡県北九州市小倉北区魚町2-2-2</dd></section>
    </body></html>
    """
    detail_page = _read_fixture("chintai_detail_facts_min.html")

    def fake_fetch_html(_session, url: str, *_args, **_kwargs):
        if url.endswith("/chintai/city/1619.html"):
            return list_page, False
        if url.endswith("/chintai/1"):
            return detail_page, False
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(crawl.requests, "Session", FakeSession)
    monkeypatch.setattr(crawl, "fetch_html", fake_fetch_html)

    _out_dir, facts_csv, stats = crawl.run_crawl(
        city_ids=["1619"],
        kinds=["chintai"],
        mode="facts",
        out_root=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        sleep_sec=0,
        max_pages=1,
        retry_count=0,
        user_agent="ua",
    )

    assert facts_csv.name.startswith("building_facts_")
    assert facts_csv.exists()
    assert stats["facts_total"] == 1


def test_parse_list_card_facts_extracts_non_kitakyushu_address() -> None:
    html = """
    <html><body>
      <section class="property-card">
        <h2>行橋サンプルレジデンス</h2>
        <a href="/chintai/123">detail</a>
        <div class="meta">所在地: 福岡県行橋市西宮市1-2-3</div>
      </section>
    </body></html>
    """
    tree = crawl.HTMLParser(html)
    card = tree.css_first("section.property-card")
    assert card is not None

    row = crawl.parse_list_card_facts(
        card,
        kind="chintai",
        detail_url="https://www.mansion-review.jp/chintai/123",
        fallback_name="fallback",
        fallback_address="",
    )

    assert row.address == "行橋市西宮市1-2-3"


def test_run_crawl_facts_fills_address_from_detail_and_records_coverage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    list_page = """
    <html><body>
      <section class="property-card">
        <h2>行橋サンプルレジデンス</h2>
        <a href="/chintai/50001">detail</a>
        <dd class="address">福岡県行橋市西宮市</dd>
      </section>
    </body></html>
    """
    detail_page = """
    <html><body>
      <h1>行橋サンプルレジデンス</h1>
      <div class="address">福岡県行橋市西宮市1-2-3</div>
    </body></html>
    """

    def fake_fetch_html(_session, url: str, *_args, **_kwargs):
        if url.endswith("/chintai/city/1639.html"):
            return list_page, False
        if url.endswith("/chintai/50001"):
            return detail_page, False
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(crawl.requests, "Session", FakeSession)
    monkeypatch.setattr(crawl, "fetch_html", fake_fetch_html)

    _out_dir, facts_csv, stats = crawl.run_crawl(
        city_ids=["1639"],
        kinds=["chintai"],
        mode="facts",
        out_root=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        sleep_sec=0,
        max_pages=1,
        retry_count=0,
        user_agent="ua",
    )

    rows = facts_csv.read_text(encoding="utf-8-sig").splitlines()
    assert any("行橋市西宮市1-2-3" in line for line in rows)
    assert stats["address_coverage"] == [
        {"city_id": "1639", "kind": "chintai", "rows": 1, "address_non_empty": 1, "address_with_digits": 1}
    ]


def test_parse_list_card_facts_bunjo_extracts_required_fields() -> None:
    html = f"<html><body>{_read_fixture('list_card_bunjo_min.html')}</body></html>"
    tree = crawl.HTMLParser(html)
    card = tree.css_first('li.property-detail-list-item')
    assert card is not None

    row = crawl.parse_list_card_facts(
        card,
        kind='mansion',
        detail_url='https://www.mansion-review.jp/mansion/12345',
        fallback_name='fallback',
        fallback_address='福岡県北九州市小倉北区浅野2-1-1',
    )

    assert row.built_year_month == '2011-02'
    assert row.sale_price_yen_avg == 40410000
    assert row.sale_price_yen_min == 39800000
    assert row.sale_price_yen_max == 42000000
    assert row.sale_area_sqm_min == 65.0
    assert row.sale_area_sqm_max == 70.1
    assert row.sale_layout_types_json == '["2LDK", "3LDK"]'
    assert row.sale_listing_count == 2
    assert row.property_kind == 'bunjo'
    assert row.structure == 'RC'


def test_parse_list_card_facts_access_info_uses_short_transport_only() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>交通抽出テスト</h3>
        <dl>
          <dt>交通</dt><dd>JR小倉駅 徒歩7分</dd>
          <dt>築年数</dt><dd>築18年</dd>
          <dt>階建て</dt><dd>11階建て</dd>
          <dt>総戸数</dt><dd>98戸</dd>
        </dl>
        <div>平均賃料 10.2万円</div>
      </li>
    </body></html>
    """
    tree = crawl.HTMLParser(html)
    card = tree.css_first("li.property-detail-list-item")
    assert card is not None

    row = crawl.parse_list_card_facts(
        card,
        kind="chintai",
        detail_url="https://www.mansion-review.jp/chintai/70001",
        fallback_name="fallback",
        fallback_address="",
    )

    assert row.access_info == "JR小倉駅 徒歩7分"
    assert row.floor_count_text == "11階建て"
    assert row.total_units == 98
