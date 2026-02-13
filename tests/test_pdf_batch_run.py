import pandas as pd

from tatemono_map.cli.pdf_batch_run import (
    apply_name_and_row_filters,
    classify_detached_house,
    should_stop_on_qc_failures,
    split_building_and_room,
)


def test_split_building_and_room_numeric_suffix():
    b, r = split_building_and_room("グランフォーレ小倉シティタワー302")
    assert b == "グランフォーレ小倉シティタワー"
    assert r == "302"


def test_split_building_and_room_keeps_building_block_suffix():
    b, r = split_building_and_room("ACハイム小倉Ⅰ号棟")
    assert b == "ACハイム小倉I号棟"
    assert r == ""


def test_split_building_and_room_go_shitsu():
    b, r = split_building_and_room("○○マンション 302号室")
    assert b == "○○マンション"
    assert r == "302"


def test_classify_detached_house():
    assert classify_detached_house("南丘貸家") is True
    assert classify_detached_house("サンプルマンション") is False


def test_apply_name_and_row_filters_drops_detached_row_only():
    df = pd.DataFrame(
        [
            {"building_name": "南丘貸家", "room": "", "address": "a"},
            {"building_name": "○○マンション 302号室", "room": "302", "address": "b"},
        ]
    )

    out, dropped, reasons = apply_name_and_row_filters(df)

    assert dropped == 1
    assert reasons["detached_house"] == 1
    assert len(out) == 1
    row = out.iloc[0]
    assert row["source_property_name"] == "○○マンション 302号室"
    assert row["building_name"] == "○○マンション"
    assert row["room_no"] == "302"


def test_qc_mode_warn_does_not_stop():
    assert should_stop_on_qc_failures("warn", failures=2) is False


def test_qc_mode_strict_stops_on_failures():
    assert should_stop_on_qc_failures("strict", failures=1) is True
