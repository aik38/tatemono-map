from pathlib import Path

import pandas as pd

from tatemono_map.cli.pdf_batch_run import (
    RealproParser,
    UlucksParser,
    apply_name_and_row_filters,
    classify_detached_house,
    detect_pdf_kind,
    is_noise_line,
    should_stop_on_qc_failures,
    split_building_and_room,
)


def _fixture(name: str) -> str:
    return (Path("tests/fixtures") / name).read_text(encoding="utf-8")


def test_split_building_and_room_numeric_suffix_needs_delimiter_or_marker():
    b, r = split_building_and_room("グランフォーレ小倉シティタワー302")
    assert b == "グランフォーレ小倉シティタワー302"
    assert r == ""


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


def test_realpro_detect_and_noise_line_filtering_fixture():
    text = _fixture("realpro_page1.txt")
    parser = RealproParser()
    detected = parser.detect_kind(text, {})
    assert detected.kind == "realpro"
    assert is_noise_line("TEL:093-000-0000")
    assert is_noise_line("2/19頁")


def test_realpro_multi_blocks_fixture_has_multiple_context_candidates():
    text = _fixture("realpro_page_multi_blocks.txt")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    building_like = [line for idx, line in enumerate(lines[:-1]) if "マンション" in line and "北九州市" in lines[idx + 1]]
    assert len(building_like) >= 2


def test_ulucks_suffix_number_fixture_keeps_building_number():
    text = _fixture("ulucks_suffix_number.txt")
    parser = UlucksParser()
    detected = parser.detect_kind(text, {})
    assert detected.kind == "ulucks"

    b, r = split_building_and_room("フェルト127")
    assert b == "フェルト127"
    assert r == ""


def test_non_vacancy_detection_fixture(tmp_path: Path):
    pdf = tmp_path / "non_vacancy.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%mock")

    # detect_pdf_kind handles parser sniff errors as non_vacancy
    out = detect_pdf_kind(pdf)
    assert out.kind == "non_vacancy"
