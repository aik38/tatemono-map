import json
import importlib.util
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO / "tests" / "fixtures" / "mansion_review_top15"
SCRIPT_PATH = REPO / "scripts" / "mansion_review_crawl_to_csv.py"

def load_truth():
    return json.loads((FIXTURE_DIR / "top15_truth.json").read_text(encoding="utf-8"))

def load_html(filename: str) -> str:
    return (FIXTURE_DIR / filename).read_text(encoding="utf-8")

def load_target_module():
    import sys
    spec = importlib.util.spec_from_file_location("mr_crawl", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

def resolve_extractor(mod):
    for name in [
        "extract_sales_rows_from_html",
        "_extract_sales_rows_from_html",
        "extract_mansion_sales_rows_from_html",
        "_extract_mansion_sales_rows_from_html",
    ]:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    pytest.fail("Extractor function is not wired in test yet.")

def norm_row(row: dict) -> dict:
    return {
        "price_text": row.get("price_text", "") or "",
        "area_text": row.get("area_text", "") or "",
        "layout": row.get("layout", "") or "",
        "floor": row.get("floor", "") or "",
        "direction": row.get("direction", "") or "",
        "is_mosaic": bool(row.get("is_mosaic", False)),
    }

@pytest.mark.parametrize("item", load_truth()["top15"])
def test_top15_card_counts(item):
    mod = load_target_module()
    extractor = resolve_extractor(mod)
    rows = [norm_row(r) for r in extractor(load_html(item["file"]))]

    assert len(rows) == item["visible_row_count"]
    assert sum(1 for r in rows if not r["is_mosaic"]) == item["visible_exact_count"]
    assert sum(1 for r in rows if r["is_mosaic"]) == item["visible_mosaic_count"]

@pytest.mark.parametrize("item", [i for i in load_truth()["top15"] if i["visible_exact_count"] > 0])
def test_top15_exact_rows_match_snapshot(item):
    mod = load_target_module()
    extractor = resolve_extractor(mod)
    rows = [norm_row(r) for r in extractor(load_html(item["file"]))]
    exact_rows = [r for r in rows if not r["is_mosaic"]]
    expected = [r for r in item["rows"] if not r["is_mosaic"]]

    for exp in expected:
        assert any(
            r["price_text"] == exp["price_text"] and
            r["area_text"] == exp["area_text"] and
            r["layout"] == exp["layout"] and
            r["floor"] == exp["floor"] and
            r["direction"] == exp["direction"]
            for r in exact_rows
        )

@pytest.mark.parametrize("item", load_truth()["top15"])
def test_no_badge_text_leaks_into_direction(item):
    mod = load_target_module()
    extractor = resolve_extractor(mod)
    rows = [norm_row(r) for r in extractor(load_html(item["file"]))]

    bad_tokens = ["高資産価値・割安", "新着", "リノベ", "リフォーム済み", "ネット公開物件", "割安", "相応"]
    for row in rows:
        for token in bad_tokens:
            assert token not in row["direction"]
