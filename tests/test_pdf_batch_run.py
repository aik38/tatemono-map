from pathlib import Path

import pandas as pd

from tatemono_map.cli.pdf_batch_run import (
    RealproParser,
    UlucksParser,
    apply_name_and_row_filters,
    classify_detached_house,
    detect_pdf_kind,
    is_mojibake,
    is_noise_line,
    normalize_pdf_text,
    restore_latin1_cp932_mojibake,
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
    assert is_noise_line("093-000-0000 TEL:093-000-0000")


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




def test_realpro_context_extraction_ignores_noise_fixture():
    text = _fixture("realpro_noise_context_trap.txt")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    parser = RealproParser()

    contexts = parser._extract_contexts(lines)

    assert contexts
    assert contexts[0][0] == "サンプルメゾン西小倉"
    assert not any("TEL" in c[0] or "FAX" in c[0] for c in contexts)
    assert not any("/" in c[0] and "頁" in c[0] for c in contexts)


def test_qc_check_realpro_requires_building_name_when_room_exists():
    from tatemono_map.cli.pdf_batch_run import qc_check

    df = pd.DataFrame([
        {"building_name": "", "room": "101", "address": "北九州市小倉北区魚町1-1", "rent_man": 7.0, "fee_man": 0.3, "floor": "1", "layout": "1K", "area_sqm": 25.0},
    ])

    reasons = qc_check(df, "realpro")
    assert "building_name_missing_with_room" in reasons

def test_non_vacancy_detection_fixture(tmp_path: Path):
    pdf = tmp_path / "non_vacancy.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%mock")

    # detect_pdf_kind handles parser sniff errors as non_vacancy
    out = detect_pdf_kind(pdf)
    assert out.kind == "non_vacancy"


def test_restore_latin1_cp932_mojibake_fixture():
    mojibake = _fixture("realpro_mojibake_pypdf.txt")
    restored = restore_latin1_cp932_mojibake(mojibake)
    expected = _fixture("realpro_mojibake_restored.txt")
    assert restored == expected


def test_is_mojibake_detection():
    assert is_mojibake("正常な日本語の文章です。") is False
    assert is_mojibake("ã‚¢ã‚¤") is True
    assert is_mojibake("����") is True


def test_realpro_detect_kind_works_after_mojibake_normalization():
    parser = RealproParser()
    mojibake = _fixture("realpro_mojibake_pypdf.txt")

    before = parser.detect_kind(mojibake, {})
    assert before.kind == "non_vacancy"

    after = parser.detect_kind(normalize_pdf_text(mojibake), {})
    assert after.kind == "realpro"


def test_realpro_parse_with_fixture_text_extracts_rows_from_table_like_content(tmp_path: Path):
    from tatemono_map.cli import pdf_batch_run as mod

    class _Page:
        def __init__(self, text: str, table: list[list[str]]):
            self._text = text
            self._table = table

        def extract_text(self):
            return self._text

        def extract_tables(self):
            return [self._table]

    class _Pdf:
        def __init__(self, pages):
            self.pages = pages

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    mojibake = _fixture("realpro_mojibake_pypdf.txt")
    page_text = "\n".join(
        [
            mojibake,
            "サンプルメゾン",
            "北九州市小倉北区魚町1-1",
            "RC造 築10年",
        ]
    )
    table = [
        ["号室名", "賃料", "共益費", "間取・面積"],
        ["101", "6.2万", "0.3万", "1K 25.0㎡"],
    ]

    original_open = mod.pdfplumber.open
    mod.pdfplumber.open = lambda _path: _Pdf([_Page(page_text, table)])
    try:
        result = RealproParser().parse(tmp_path / "dummy.pdf")
    finally:
        mod.pdfplumber.open = original_open

    assert len(result.df) > 0


def test_realpro_table_bbox_context_fixture_extracts_building_name_and_address(tmp_path: Path):
    from tatemono_map.cli import pdf_batch_run as mod

    context = _fixture("realpro_context_block.txt")

    class _Table:
        bbox = (0.0, 220.0, 500.0, 700.0)

        def extract(self):
            return [
                ["号室名", "賃料", "共益費", "間取・面積"],
                ["101", "6.2万", "0.3万", "1K 25.0㎡"],
            ]

    class _Page:
        def extract_text(self):
            return "空室一覧表"

        def find_tables(self):
            return [_Table()]

        def extract_words(self, **_kwargs):
            lines = context.splitlines()
            out = []
            for i, line in enumerate(lines):
                out.append({"text": line, "x0": 10.0, "top": 120.0 + i * 16, "x1": 480.0, "bottom": 132.0 + i * 16})
            return out

    class _Pdf:
        pages = [_Page()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    original_open = mod.pdfplumber.open
    mod.pdfplumber.open = lambda _path: _Pdf()
    try:
        result = RealproParser().parse(tmp_path / "dummy.pdf")
    finally:
        mod.pdfplumber.open = original_open

    assert len(result.df) == 1
    assert result.df.iloc[0]["building_name"] == "LEGEND鍛冶町"
    assert "北九州市小倉北区" in result.df.iloc[0]["address"]


def test_ulucks_address_complements_city_ward_from_ward_hint(tmp_path: Path):
    from tatemono_map.cli import pdf_batch_run as mod

    class _Page:
        def extract_text(self):
            return "小倉北区 空室一覧"

        def extract_tables(self):
            return [[
                ["物件名", "所在地", "号室", "賃料", "共益費", "間取詳細", "面積", "構造"],
                ["LEGEND鍛冶町", "鍛冶町２丁目3-5", "101", "6.2万", "0.3万", "1K:詳細", "25.0㎡", "RC"],
            ]]

    class _Pdf:
        pages = [_Page()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    original_open = mod.pdfplumber.open
    mod.pdfplumber.open = lambda _path: _Pdf()
    try:
        result = UlucksParser().parse(tmp_path / "dummy.pdf")
    finally:
        mod.pdfplumber.open = original_open

    assert "北九州市小倉北区" in result.df.iloc[0]["address"]
