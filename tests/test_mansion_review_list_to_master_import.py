import csv
import importlib.util
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "mansion_review_list_to_master_import.py"
SPEC = importlib.util.spec_from_file_location("mansion_review_list_to_master_import", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
convert = module.convert


def test_convert_maps_chintai_and_mansion_rows_without_shared_changes(tmp_path) -> None:
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
                "repair_fund_text",
                "deposit_text",
                "key_money_text",
                "layout_text",
                "area_text",
                "floor_text",
                "direction_text",
                "access_text",
                "built_text",
                "building_floor_count_text",
                "total_units_text",
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
                "price_or_rent_text": "7.8万円",
                "fee_text": "5,000円",
                "repair_fund_text": "",
                "deposit_text": "1ヶ月",
                "key_money_text": "2ヶ月",
                "layout_text": "1LDK",
                "area_text": "41.2㎡",
                "floor_text": "3階",
                "direction_text": "南",
                "access_text": "JR小倉駅 徒歩5分",
                "built_text": "築16年",
                "building_floor_count_text": "10階建て",
                "total_units_text": "45戸",
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
                "fee_text": "9,000円",
                "repair_fund_text": "7,000円",
                "deposit_text": "",
                "key_money_text": "",
                "layout_text": "3LDK",
                "area_text": "71.3㎡",
                "floor_text": "10階",
                "direction_text": "東",
                "access_text": "JR小倉駅 徒歩7分",
                "built_text": "築12年",
                "building_floor_count_text": "14階建て",
                "total_units_text": "120戸",
            }
        )

    count = convert(input_csv, output_csv, "2026/04/05 12:00")
    assert count == 2

    with output_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    rental = rows[0]
    assert rental["category"] == "chintai"
    assert rental["rent_man"] == "7.8"
    assert rental["fee_man"] == "0.5"
    assert "交通:JR小倉駅 徒歩5分" in rental["raw_block"]
    assert "敷金:1ヶ月" in rental["raw_block"]
    assert "礼金:2ヶ月" in rental["raw_block"]

    sale = rows[1]
    assert sale["category"] == "mansion"
    assert sale["rent_man"] == "3180"
    assert sale["fee_man"] == "0.9"
    assert "管理費:9,000円" in sale["raw_block"]
    assert "修繕積立金:7,000円" in sale["raw_block"]
