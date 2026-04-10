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


def test_parse_list_page_chintai_uses_recommend_row_and_splits_rent_fee() -> None:
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
          <thead>
            <tr><th>賃料</th><th>管理費</th><th>敷金</th><th>礼金</th><th>専有面積</th><th>間取り</th></tr>
          </thead>
          <tbody class="recommend_row">
            <tr><td>7.8万円</td><td>5,000円</td><td>1ヶ月</td><td>2ヶ月</td><td>41.2㎡</td><td>1LDK</td></tr>
            <tr><td>8.4万円</td><td>6,000円</td><td>1ヶ月</td><td>2ヶ月</td><td>44.2㎡</td><td>2LDK</td></tr>
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
    assert len(rows) == 2
    assert debug.selector_hits["rows"] == 2

    first = rows[0]
    assert first.address == "福岡県北九州市門司区港町1-2-3"
    assert first.access_text == "JR門司港駅 徒歩8分"
    assert first.built_text == "築16年"
    assert first.building_floor_count_text == "10階建て"
    assert first.total_units_text == "45戸"
    assert first.price_or_rent_text == "7.8万円"
    assert first.fee_text == "5,000円"
    assert first.deposit_text == "1ヶ月"
    assert first.key_money_text == "2ヶ月"
    assert first.area_text == "41.2㎡"
    assert first.layout_text == "1LDK"


def test_parse_list_page_mansion_uses_price_tsubo_area_layout_floor_direction() -> None:
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
          <thead>
            <tr><th>価格</th><th>坪単価</th><th>専有面積</th><th>間取り</th><th>所在階</th><th>向き</th></tr>
          </thead>
          <tbody class="recommend_row">
            <tr><td>3,180万円</td><td>159万円/坪</td><td>66.0㎡</td><td>2LDK</td><td>7階</td><td>南</td></tr>
            <tr><td>4,200万円</td><td>192万円/坪</td><td>72.0㎡</td><td>3LDK</td><td>10階</td><td>東</td></tr>
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
    assert len(rows) == 2
    assert rows[0].price_or_rent_text == "3,180万円"
    assert rows[0].tsubo_unit_price_text == "159万円/坪"
    assert rows[0].area_text == "66.0㎡"
    assert rows[0].layout_text == "2LDK"
    assert rows[0].floor_text == "7階"
    assert rows[0].direction_text == "南"
    assert rows[0].fee_text == ""


def test_parse_list_page_chintai_without_table_header_uses_fixed_row_order() -> None:
    html = """
    <html><body>
      <li class="property-detail-list-item">
        <h3>門司ヘッダなしレジデンス</h3>
        <div class="property-detail-content_main">
          <dl>
            <dt>住所</dt><dd>福岡県北九州市門司区東本町1-1-1</dd>
            <dt>交通</dt><dd>JR門司港駅 徒歩9分</dd>
            <dt>築年数</dt><dd>築18年</dd>
            <dt>階建て</dt><dd>9階建て</dd>
            <dt>総戸数</dt><dd>30戸</dd>
          </dl>
        </div>
        <table class="recommendTable">
          <tbody class="recommend_row">
            <tr><td>6.8万円</td><td>4,000円</td><td>1ヶ月</td><td>1ヶ月</td><td>33.5㎡</td><td>1DK</td></tr>
          </tbody>
        </table>
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
    assert len(rows) == 1
    assert rows[0].price_or_rent_text == "6.8万円"
    assert rows[0].fee_text == "4,000円"
    assert rows[0].deposit_text == "1ヶ月"
    assert rows[0].key_money_text == "1ヶ月"
    assert rows[0].area_text == "33.5㎡"
    assert rows[0].layout_text == "1DK"


def test_parse_list_page_mansion_without_table_header_uses_fixed_row_order() -> None:
    html = """
    <html><body>
      <article class="property-detail-list-item">
        <h3>門司ヘッダなし分譲</h3>
        <div class="property-detail-content_main">
          <table>
            <tr><th>住所</th><td>福岡県北九州市門司区東港町7-8-9</td></tr>
            <tr><th>交通</th><td>JR門司港駅 徒歩6分</td></tr>
            <tr><th>築年数</th><td>築14年</td></tr>
            <tr><th>階建て</th><td>14階建て</td></tr>
            <tr><th>総戸数</th><td>85戸</td></tr>
          </table>
        </div>
        <table class="recommendTable">
          <tbody class="recommend_row">
            <tr><td>2,980万円</td><td>139万円/坪</td><td>63.0㎡</td><td>2LDK</td><td>8階</td><td>南西</td></tr>
          </tbody>
        </table>
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
    assert len(rows) == 1
    assert rows[0].price_or_rent_text == "2,980万円"
    assert rows[0].tsubo_unit_price_text == "139万円/坪"
    assert rows[0].area_text == "63.0㎡"
    assert rows[0].layout_text == "2LDK"
    assert rows[0].floor_text == "8階"
    assert rows[0].direction_text == "南西"


def test_parse_list_page_does_not_use_property_card_fallback() -> None:
    html = """
    <html><body>
      <section class="property-card">
        <h2 class="property-name">旧形式カード</h2>
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
    assert debug.selector_hits["cards"] == 0


def test_parse_max_page_from_links() -> None:
    html = """
    <html><body>
      <a href="/chintai/city/1619.html">1</a>
      <a href="/chintai/city/1619_2.html">2</a>
      <a href="/chintai/city/1619_55.html">55</a>
    </body></html>
    """
    assert parse_max_page(html, kind="chintai", city_id="1619") == 55
