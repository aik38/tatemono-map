import csv

from scripts.mansion_review_list_to_master_import import _sanitize_mansion_review_layout, convert


def test_sanitize_layout_accepts_valid_patterns() -> None:
    assert _sanitize_mansion_review_layout("ワンルーム") == "ワンルーム"
    assert _sanitize_mansion_review_layout("1LDK") == "1LDK"
    assert _sanitize_mansion_review_layout("2SLDK") == "2SLDK"
    assert _sanitize_mansion_review_layout("3LDK+S") == "3LDK+S"


def test_sanitize_layout_rejects_polluted_text() -> None:
    bad = "住所・交通・築年数・総戸数・賃料表・号室・全 件を表示する・function()"
    assert _sanitize_mansion_review_layout(bad) == ""
    assert _sanitize_mansion_review_layout("<script>alert(1)</script>") == ""
    assert _sanitize_mansion_review_layout("2LDK 号室") == ""


def test_sanitize_layout_rejects_polluted_text_for_sale_too() -> None:
    bad = "価格表 全 件を表示する function(){return false;}"
    assert _sanitize_mansion_review_layout(bad) == ""


def test_convert_flows_fee_man_and_raw_block_labels(tmp_path) -> None:
    input_csv = tmp_path / "mansion_review_list_20260405_120000.csv"
    output_csv = tmp_path / "mansion_review_master_import.csv"
    with input_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "kind",
                "ward",
                "page_url",
                "detail_url",
                "building_name",
                "address",
                "price_or_rent_text",
                "fee_text",
                "deposit_text",
                "key_money_text",
                "layout_text",
                "area_text",
                "floor_text",
                "direction_text",
                "access_text",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "kind": "chintai",
                "ward": "小倉北区",
                "page_url": "https://www.mansion-review.jp/chintai/city/1619.html",
                "detail_url": "https://www.mansion-review.jp/chintai/90001",
                "building_name": "サンプルレジデンス",
                "address": "北九州市小倉北区魚町1-2-3",
                "price_or_rent_text": "7.8万円(5,000円)",
                "fee_text": "5,000円",
                "deposit_text": "1ヶ月",
                "key_money_text": "2ヶ月",
                "layout_text": "1LDK",
                "area_text": "41.2㎡",
                "floor_text": "3階",
                "direction_text": "南",
                "access_text": "JR小倉駅 徒歩5分",
            }
        )
        writer.writerow(
            {
                "kind": "mansion",
                "ward": "小倉北区",
                "page_url": "https://www.mansion-review.jp/mansion/city/1619.html",
                "detail_url": "https://www.mansion-review.jp/mansion/80001",
                "building_name": "分譲サンプル",
                "address": "北九州市小倉北区浅野2-1-1",
                "price_or_rent_text": "3,180万円",
                "fee_text": "",
                "deposit_text": "",
                "key_money_text": "",
                "layout_text": "住所・交通・築年数・総戸数・賃料表・号室・全 件を表示する・function()",
                "area_text": "71.3㎡",
                "floor_text": "10階",
                "direction_text": "東",
                "access_text": "JR小倉駅 徒歩7分",
            }
        )

    count = convert(input_csv, output_csv, "2026/04/05 12:00")
    assert count == 2
    with output_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    rental = rows[0]
    assert rental["fee_man"] == "0.5"
    assert "管理費/共益費:5,000円" in rental["raw_block"]
    assert "敷金:1ヶ月" in rental["raw_block"]
    assert "礼金:2ヶ月" in rental["raw_block"]
    assert "交通:JR小倉駅 徒歩5分" in rental["raw_block"]
    assert "向き:南" in rental["raw_block"]
    assert "所在階:3階" in rental["raw_block"]

    sale = rows[1]
    assert sale["layout"] == ""
