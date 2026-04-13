import importlib.util
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "mansion_review_crawl_to_csv.py"
SPEC = importlib.util.spec_from_file_location("mansion_review_crawl_to_csv", MODULE_PATH)
assert SPEC and SPEC.loader
crawl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = crawl
SPEC.loader.exec_module(crawl)

parse_list_page = crawl.parse_list_page
parse_max_page = crawl.parse_max_page
ListRow = crawl.ListRow
_to_master_rows = crawl._to_master_rows


def test_parse_list_page_chintai_extracts_required_11_fields() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>門司テストレジデンス</h3>
        <div class="property-detail-content_main">
          <dl>
            <dt>住所</dt><dd>福岡県北九州市門司区港町1-2-3</dd>
            <dt>交通</dt><dd>JR門司港駅 徒歩8分</dd>
            <dt>築年数</dt><dd>築16年</dd>
            <dt>階建て</dt><dd>10階建て</dd>
            <dt>総戸数</dt><dd>45戸</dd>
          </dl>
        </div>
        <table class="recommendTable">
          <tbody class="recommend_row">
            <tr>
              <td data-th="賃料">7.8万円</td>
              <td data-th="管理費">5,000円</td>
              <td data-th="敷金">1ヶ月</td>
              <td data-th="礼金">2ヶ月</td>
              <td data-th="専有面積">41.2㎡</td>
              <td data-th="間取り">1LDK</td>
            </tr>
          </tbody>
        </table>
        <a href="/chintai/91001">詳細</a>
      </li>
    </body></html>
    """
    rows, debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        kind="chintai",
        city_id="1616",
        page_no=1,
    )
    assert debug["rows"] == 1
    row = rows[0]
    assert row.address == "福岡県北九州市門司区港町1-2-3"
    assert row.access_text == "JR門司港駅 徒歩8分"
    assert row.built_text == "築16年"
    assert row.building_floor_count_text == "10階建て"
    assert row.total_units_text == "45戸"
    assert row.price_or_rent_text == "7.8万円"
    assert row.fee_text == "5,000円"
    assert row.deposit_text == "1ヶ月"
    assert row.key_money_text == "2ヶ月"
    assert row.area_text == "41.2㎡"
    assert row.layout_text == "1LDK"


def test_parse_list_page_mansion_extracts_required_11_fields() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <h3>コクラタワー</h3>
        <div class="property-detail-content_main">
          <table>
            <tr><th>住所</th><td>福岡県北九州市小倉北区浅野2-1-1</td></tr>
            <tr><th>交通</th><td>JR小倉駅 徒歩7分</td></tr>
            <tr><th>築年数</th><td>築12年</td></tr>
            <tr><th>階建て</th><td>20階建て</td></tr>
            <tr><th>総戸数</th><td>120戸</td></tr>
          </table>
        </div>
        <table class="recommendTable">
          <tbody class="recommend_row">
            <tr>
              <td data-th="価格">3,180万円</td>
              <td data-th="坪単価">159万円/坪</td>
              <td data-th="専有面積">66.0㎡</td>
              <td data-th="間取り">2LDK</td>
              <td data-th="所在階">7階</td>
              <td data-th="向き">南</td>
            </tr>
          </tbody>
        </table>
        <a href="/mansion/80011">物件詳細</a>
      </article>
    </body></html>
    """
    rows, _ = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1619.html",
        kind="mansion",
        city_id="1619",
        page_no=1,
    )
    row = rows[0]
    assert row.address == "福岡県北九州市小倉北区浅野2-1-1"
    assert row.access_text == "JR小倉駅 徒歩7分"
    assert row.built_text == "築12年"
    assert row.building_floor_count_text == "20階建て"
    assert row.total_units_text == "120戸"
    assert row.price_or_rent_text == "3,180万円"
    assert row.tsubo_unit_price_text == "48.18万円/m²"
    assert row.area_text == "66.0㎡"
    assert row.layout_text == "2LDK"
    assert row.floor_text == "7階"
    assert row.direction_text == "南"


def test_parse_list_page_headerless_uses_fixed_column_order() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <div class="property-detail-content_main"></div>
        <table class="recommendTable"><tbody class="recommend_row">
          <tr><td>2,980万円</td><td>139万円/坪</td><td>63.0㎡</td><td>2LDK</td><td>8階</td><td>南西</td></tr>
        </tbody></table>
      </article>
    </body></html>
    """
    rows, _ = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1616.html",
        kind="mansion",
        city_id="1616",
        page_no=1,
    )
    assert rows[0].price_or_rent_text == "2,980万円"
    assert rows[0].tsubo_unit_price_text == "47.3万円/m²"
    assert rows[0].area_text == "63.0㎡"
    assert rows[0].layout_text == "2LDK"
    assert rows[0].floor_text == "8階"
    assert rows[0].direction_text == "南西"


def test_parse_list_page_mansion_ignores_leading_decorative_cells() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <h3>コクラタワー</h3>
        <div class="property-detail-content_main"></div>
        <table class="recommendTable"><tbody class="recommend_row">
          <tr>
            <td>新着</td><td>リノベ</td><td>コクラタワー</td><td>1302号室</td>
            <td>3,180万円</td><td>159万円/坪</td><td>66.0㎡</td><td>2LDK</td><td>7階</td><td>南</td>
          </tr>
        </tbody></table>
      </article>
    </body></html>
    """
    rows, _ = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1619.html",
        kind="mansion",
        city_id="1619",
        page_no=1,
    )
    row = rows[0]
    assert row.price_or_rent_text == "3,180万円"
    assert row.tsubo_unit_price_text == "48.18万円/m²"
    assert row.area_text == "66.0㎡"
    assert row.layout_text == "2LDK"
    assert row.floor_text == "7階"
    assert row.direction_text == "南"


def test_parse_list_page_mansion_does_not_treat_layout_as_direction_on_shifted_column() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <h3>パサージュ門司</h3>
        <div class="property-detail-content_main"></div>
        <table class="recommendTable"><tbody class="recommend_row">
          <tr>
            <td data-th="価格">1,980万円</td>
            <td data-th="専有面積">41.2㎡</td>
            <td data-th="間取り">1R</td>
            <td data-th="所在階">5階</td>
            <td data-th="向き">ワンルーム</td>
          </tr>
        </tbody></table>
      </article>
    </body></html>
    """
    rows, _ = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1616.html",
        kind="mansion",
        city_id="1616",
        page_no=1,
    )
    row = rows[0]
    assert row.layout_text == "1R"
    assert row.floor_text == "5階"
    assert row.direction_text == ""


def test_parse_list_page_chintai_combined_cells_are_split() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>門司港レジデンス</h3>
        <div class="property-detail-content_main">
          <dl>
            <dt>住所</dt><dd>福岡県北九州市門司区東港町1-2</dd>
            <dt>交通</dt><dd>JR門司港駅 徒歩6分</dd>
            <dt>築年数</dt><dd>築10年</dd>
            <dt>階建て</dt><dd>14階建</dd>
            <dt>総戸数</dt><dd>88戸</dd>
          </dl>
        </div>
        <table class="recommendTable"><tbody class="recommend_row">
          <tr>
            <td data-th="賃料（管理費等）">8.2万円（管理費 6,000円）</td>
            <td data-th="敷/礼">1ヶ月/2ヶ月</td>
            <td data-th="専有面積">45.1㎡</td>
            <td data-th="間取り">1LDK</td>
          </tr>
        </tbody></table>
      </li>
    </body></html>
    """
    rows, _ = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        kind="chintai",
        city_id="1616",
        page_no=1,
    )
    row = rows[0]
    assert row.price_or_rent_text == "8.2万円"
    assert row.fee_text == "6,000円"
    assert row.deposit_text == "1ヶ月"
    assert row.key_money_text == "2ヶ月"
    assert row.area_text == "45.1㎡"
    assert row.layout_text == "1LDK"


def test_parse_list_page_chintai_ignores_leading_decorative_cells() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>門司港レジデンス</h3>
        <div class="property-detail-content_main"></div>
        <table class="recommendTable"><tbody class="recommend_row">
          <tr>
            <td>新着</td><td>門司港レジデンス</td><td>203号室</td>
            <td>8.2万円</td><td>6,000円</td><td>1ヶ月</td><td>2ヶ月</td><td>45.1㎡</td><td>1LDK</td>
          </tr>
        </tbody></table>
      </li>
    </body></html>
    """
    rows, _ = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        kind="chintai",
        city_id="1616",
        page_no=1,
    )
    row = rows[0]
    assert row.price_or_rent_text == "8.2万円"
    assert row.fee_text == "6,000円"
    assert row.deposit_text == "1ヶ月"
    assert row.key_money_text == "2ヶ月"
    assert row.area_text == "45.1㎡"
    assert row.layout_text == "1LDK"


def test_parse_list_page_does_not_use_non_target_card_selector() -> None:
    html = """
    <html><body>
      <section class="property-card">
        <table class="recommendTable"><tbody class="recommend_row"><tr><td>1</td></tr></tbody></table>
      </section>
    </body></html>
    """
    rows, debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/chintai/city/1619.html",
        kind="chintai",
        city_id="1619",
        page_no=1,
    )
    assert rows == []
    assert debug["cards"] == 0


def test_parse_max_page_from_links() -> None:
    html = """
    <html><body>
      <a href="/chintai/city/1619.html">1</a>
      <a href="/chintai/city/1619_2.html">2</a>
      <a href="/chintai/city/1619_55.html">55</a>
    </body></html>
    """
    assert parse_max_page(html, kind="chintai", city_id="1619") == 55


def test_to_master_rows_splits_chintai_rent_and_fee_from_combined_text() -> None:
    row = ListRow(
        kind="chintai",
        city_id="1616",
        ward="門司区",
        city_page="1616_1",
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        detail_url="https://www.mansion-review.jp/chintai/1",
        building_name="テスト",
        address="福岡県北九州市門司区1-1-1",
        access_text="JR徒歩1分",
        built_text="築10年",
        building_floor_count_text="10階建",
        total_units_text="30戸",
        price_or_rent_text="6.5万円 (4,000円)",
        fee_text="",
        tsubo_unit_price_text="",
        deposit_text="1ヶ月",
        key_money_text="1ヶ月",
        area_text="25.0㎡",
        layout_text="1K",
        floor_text="",
        direction_text="",
    )
    master = _to_master_rows([row], "2026/04/01 10:00")[0]
    assert master["rent_man"] == "6.5"
    assert master["fee_man"] == "0.4"


def test_to_master_rows_sets_empty_fee_when_combined_text_has_hyphen_yen() -> None:
    row = ListRow(
        kind="chintai",
        city_id="1616",
        ward="門司区",
        city_page="1616_1",
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        detail_url="https://www.mansion-review.jp/chintai/1",
        building_name="テスト",
        address="福岡県北九州市門司区1-1-1",
        access_text="JR徒歩1分",
        built_text="築10年",
        building_floor_count_text="10階建",
        total_units_text="30戸",
        price_or_rent_text="10.8万円 (-円)",
        fee_text="",
        tsubo_unit_price_text="",
        deposit_text="1ヶ月",
        key_money_text="1ヶ月",
        area_text="25.0㎡",
        layout_text="1K",
        floor_text="",
        direction_text="",
    )
    master = _to_master_rows([row], "2026/04/01 10:00")[0]
    assert master["rent_man"] == "10.8"
    assert master["fee_man"] == ""


def test_to_master_rows_sets_empty_fee_when_combined_text_has_fullwidth_hyphen_yen() -> None:
    row = ListRow(
        kind="chintai",
        city_id="1616",
        ward="門司区",
        city_page="1616_1",
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        detail_url="https://www.mansion-review.jp/chintai/1",
        building_name="テスト",
        address="福岡県北九州市門司区1-1-1",
        access_text="JR徒歩1分",
        built_text="築10年",
        building_floor_count_text="10階建",
        total_units_text="30戸",
        price_or_rent_text="10.8万円 (－円)",
        fee_text="",
        tsubo_unit_price_text="",
        deposit_text="1ヶ月",
        key_money_text="1ヶ月",
        area_text="25.0㎡",
        layout_text="1K",
        floor_text="",
        direction_text="",
    )
    master = _to_master_rows([row], "2026/04/01 10:00")[0]
    assert master["rent_man"] == "10.8"
    assert master["fee_man"] == ""


def test_to_master_rows_sets_empty_fee_when_combined_text_has_nashi_or_mu() -> None:
    row_nashi = ListRow(
        kind="chintai",
        city_id="1616",
        ward="門司区",
        city_page="1616_1",
        page_url="https://www.mansion-review.jp/chintai/city/1616.html",
        detail_url="https://www.mansion-review.jp/chintai/1",
        building_name="テスト",
        address="福岡県北九州市門司区1-1-1",
        access_text="JR徒歩1分",
        built_text="築10年",
        building_floor_count_text="10階建",
        total_units_text="30戸",
        price_or_rent_text="12万円 (無し)",
        fee_text="",
        tsubo_unit_price_text="",
        deposit_text="1ヶ月",
        key_money_text="1ヶ月",
        area_text="25.0㎡",
        layout_text="1K",
        floor_text="",
        direction_text="",
    )
    row_mu = ListRow(
        **{**row_nashi.__dict__, "price_or_rent_text": "12万円 (無)"}
    )
    master_nashi = _to_master_rows([row_nashi], "2026/04/01 10:00")[0]
    master_mu = _to_master_rows([row_mu], "2026/04/01 10:00")[0]
    assert master_nashi["fee_man"] == ""
    assert master_mu["fee_man"] == ""


def test_parse_list_page_mansion_removes_script_noise_from_cells() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <h3>ノイズテストマンション</h3>
        <table class="recommendTable"><tbody class="recommend_row">
          <tr>
            <td data-th="価格">3,680万円</td>
            <td data-th="専有面積">71.2㎡</td>
            <td data-th="間取り">3LDK<script>window.alert('x')</script></td>
            <td data-th="所在階">10階</td>
            <td data-th="向き">南</td>
          </tr>
        </tbody></table>
      </article>
    </body></html>
    """
    rows, _ = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1619.html",
        kind="mansion",
        city_id="1619",
        page_no=1,
    )
    assert rows[0].layout_text == "3LDK"


def test_parse_list_page_mansion_badge_cells_do_not_shift_columns() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <h3>バッジ混入テスト</h3>
        <table class="recommendTable"><tbody class="recommend_row">
          <tr>
            <td>新着</td><td>割安</td>
            <td>4,280万円</td><td>72.0㎡</td><td>3LDK</td><td>12階</td><td>南東</td>
          </tr>
        </tbody></table>
      </article>
    </body></html>
    """
    rows, _ = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1619.html",
        kind="mansion",
        city_id="1619",
        page_no=1,
    )
    row = rows[0]
    assert row.price_or_rent_text == "4,280万円"
    assert row.area_text == "72.0㎡"
    assert row.layout_text == "3LDK"
    assert row.floor_text == "12階"
    assert row.direction_text == "南東"


def test_to_master_rows_mansion_keeps_mosaic_price_row_with_null_price() -> None:
    row = ListRow(
        kind="mansion",
        city_id="1619",
        ward="小倉北区",
        city_page="1619_1",
        page_url="https://www.mansion-review.jp/mansion/city/1619.html",
        detail_url="https://www.mansion-review.jp/mansion/1",
        building_name="モザイク価格マンション",
        address="福岡県北九州市小倉北区1-1-1",
        access_text="JR徒歩1分",
        built_text="築8年",
        building_floor_count_text="15階建",
        total_units_text="80戸",
        price_or_rent_text="3,000万円台",
        fee_text="",
        tsubo_unit_price_text="",
        deposit_text="",
        key_money_text="",
        area_text="68.0㎡",
        layout_text="3LDK",
        floor_text="8階",
        direction_text="南",
    )
    master = _to_master_rows([row], "2026/04/01 10:00")[0]
    assert master["building_name"] == "モザイク価格マンション"
    assert master["rent_man"] == ""
    assert master["layout"] == "3LDK"


def test_parse_list_page_mansion_building_name_drops_room_suffix() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <h3>ライブスクエア小倉駅オーシャンテラス508号</h3>
        <table class="recommendTable"><tbody class="recommend_row">
          <tr>
            <td data-th="価格">4,980万円</td>
            <td data-th="専有面積">81.0㎡</td>
            <td data-th="間取り">3LDK</td>
            <td data-th="所在階">5階</td>
            <td data-th="向き">南</td>
          </tr>
        </tbody></table>
      </article>
    </body></html>
    """
    rows, _ = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1619.html",
        kind="mansion",
        city_id="1619",
        page_no=1,
    )
    assert rows[0].building_name == "ライブスクエア小倉駅オーシャンテラス"


def test_parse_list_page_mansion_static_sales_table_is_selected_by_title() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <h3>門司テストマンション</h3>
        <div class="js_sales_recommend">
          <div class="suumoRecommendBlockSearch">
            <table class="recommendTable">
              <tr class="recommend_head"><th>このマンションの【中古】販売情報</th></tr>
              <tbody class="recommend_row">
                <tr>
                  <td data-th="価格">2,980万円</td>
                  <td data-th="専有面積">63.0㎡</td>
                  <td data-th="間取り">2LDK</td>
                  <td data-th="所在階">8階</td>
                  <td data-th="向き">南西</td>
                </tr>
              </tbody>
            </table>
            <table class="recommendTable">
              <tr class="recommend_head"><th>この物件の新着が出たら教えて</th></tr>
              <tbody class="recommend_row"><tr><td>通知</td></tr></tbody>
            </table>
          </div>
        </div>
      </article>
    </body></html>
    """
    rows, debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1616.html",
        kind="mansion",
        city_id="1616",
        page_no=1,
    )
    assert debug["rows"] == 1
    assert rows[0].price_or_rent_text == "2,980万円"
    assert rows[0].layout_text == "2LDK"


def test_parse_list_page_mansion_mosaic_row_is_kept_with_null_price() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <h3>小倉モザイクマンション</h3>
        <div class="js_sales_recommend">
          <table class="recommendTable">
            <tr class="recommend_head"><th>このマンションの【中古】販売情報</th></tr>
            <tbody class="recommend_row">
              <tr>
                <td data-th="価格">3,000万円台</td>
                <td colspan="5" class="mosaic_cell">無料会員登録でモザイクを消す</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </body></html>
    """
    rows, debug = parse_list_page(
        html,
        page_url="https://www.mansion-review.jp/mansion/city/1619.html",
        kind="mansion",
        city_id="1619",
        page_no=1,
    )
    assert debug["rows"] == 1
    assert rows[0].price_or_rent_text == ""
    assert rows[0].area_text == ""
    assert rows[0].layout_text == ""
