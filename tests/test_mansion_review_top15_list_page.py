import json
import importlib.util
from pathlib import Path
from collections import OrderedDict

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO / "tests" / "fixtures" / "mansion_review_top15"
SCRIPT_PATH = REPO / "scripts" / "mansion_review_crawl_to_csv.py"

def load_truth():
    return json.loads((FIXTURE_DIR / "top15_truth.json").read_text(encoding="utf-8"))

def load_target_module():
    import sys
    spec = importlib.util.spec_from_file_location("mr_crawl", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

def test_parse_list_page_top15_order_and_counts():
    mod = load_target_module()
    html = (FIXTURE_DIR / "fixture_source.html").read_text(encoding="utf-8")
    rows, _debug = mod.parse_list_page(
        html=html,
        page_url="https://www.mansion-review.jp/mansion/city/1619.html",
        kind="mansion",
        city_id="1619",
        page_no=1,
    )

    first_seen = OrderedDict()
    counts = {}
    for row in rows:
        name = getattr(row, "building_name", "")
        if not name:
            continue
        if name not in first_seen:
            first_seen[name] = True
        counts[name] = counts.get(name, 0) + 1

    top15_names = list(first_seen.keys())[:15]
    expected = load_truth()["top15"]

    assert top15_names == [i["building_name"] for i in expected]
    for item in expected:
        assert counts.get(item["building_name"], 0) == item["visible_row_count"]

    banned = {"朝日プラザ小倉足立", "ペルル日明"}
    assert banned.isdisjoint(set(top15_names))
