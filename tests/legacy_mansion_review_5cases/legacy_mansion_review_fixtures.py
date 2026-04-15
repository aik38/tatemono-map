import json
import importlib.util
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO / "tests" / "fixtures" / "mansion_review"
SCRIPT_PATH = REPO / "scripts" / "mansion_review_crawl_to_csv.py"

def load_truth():
    return json.loads((FIXTURE_DIR / "truth.json").read_text(encoding="utf-8"))

def load_html(slug: str) -> str:
    return (FIXTURE_DIR / f"{slug}.html").read_text(encoding="utf-8")

def load_target_module():
    import sys
    # リポジトリのルートをパスに追加して、通常のimportができるようにする
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    
    # 通常のimportを使用する
    import scripts.mansion_review_crawl_to_csv as mr_crawl
    return mr_crawl

def resolve_extractor(mod):
    candidates = [
        "extract_mansion_sales_rows_from_html",
        "_extract_mansion_sales_rows_from_html",
        "extract_sales_rows_from_html",
        "_extract_sales_rows_from_html",
    ]
    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    pytest.fail("Extractor function is not wired in test yet. Add a small HTML->sales_rows wrapper in scripts/mansion_review_crawl_to_csv.py")

def resolve_master_mapper(mod):
    candidates = [
        "to_master_rows_from_sales_rows",
        "_to_master_rows_from_sales_rows",
        "to_master_rows",
        "_to_master_rows",
    ]
    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    pytest.fail("Master-row mapper is not wired in test yet. Expose a small sales_rows->master_rows wrapper in scripts/mansion_review_crawl_to_csv.py")

def norm(row: dict) -> dict:
    return {
        "price_text": row.get("price_text", "") or "",
        "area_text": row.get("area_text", "") or "",
        "layout": row.get("layout", "") or "",
        "floor": row.get("floor", "") or "",
        "direction": row.get("direction", "") or "",
        "is_mosaic": bool(row.get("is_mosaic", False)),
    }

@pytest.mark.parametrize(
    "slug",
    [
        "01_kokura_dc_tower",
        "02_sunpark_kokura_tower_residence",
        "03_live_square_ocean_terrace",
        "04_sunrelius_kokura_ekiminami",
        "05_livio_city_nakai_eastcourt",
    ],
)
def test_target_table_scope_and_counts(slug):
    truth = load_truth()[slug]
    html = load_html(slug)

    mod = load_target_module()
    extractor = resolve_extractor(mod)

    rows = extractor(html)
    rows = [norm(r) for r in rows]

    assert len(rows) == truth["total_count"]

    exact_rows = [r for r in rows if not r["is_mosaic"]]
    mosaic_rows = [r for r in rows if r["is_mosaic"]]

    assert len(exact_rows) == truth["exact_count"]
    assert len(mosaic_rows) == truth["mosaic_count"]

def test_mosaic_rows_do_not_carry_values():
    html = load_html("01_kokura_dc_tower")
    mod = load_target_module()
    extractor = resolve_extractor(mod)

    rows = extractor(html)
    rows = [norm(r) for r in rows]

    assert len(rows) == 1
    row = rows[0]
    assert row["is_mosaic"] is True
    assert row["area_text"] == ""
    assert row["layout"] == ""
    assert row["floor"] == ""
    assert row["direction"] == ""

def test_badge_text_is_not_used_as_direction():
    html = load_html("04_sunrelius_kokura_ekiminami")
    mod = load_target_module()
    extractor = resolve_extractor(mod)

    rows = extractor(html)
    rows = [norm(r) for r in rows]

    forbidden = [
        "高資産価値・割安",
        "新着",
        "リノベ",
        "リフォーム済み",
        "サンレリウス小倉駅南",
    ]

    for row in rows:
        for token in forbidden:
            assert token not in row["direction"]

def test_livio_exact_rows_match_truth():
    truth = load_truth()["05_livio_city_nakai_eastcourt"]
    html = load_html("05_livio_city_nakai_eastcourt")

    mod = load_target_module()
    extractor = resolve_extractor(mod)

    rows = extractor(html)
    rows = [norm(r) for r in rows]
    exact_rows = [r for r in rows if not r["is_mosaic"]]

    assert len(exact_rows) == 2

    for expected in truth["exact_rows"]:
        assert any(
            r["price_text"] == expected["price_text"]
            and r["area_text"] == expected["area_text"]
            and r["layout"] == expected["layout"]
            and r["floor"] == expected["floor"]
            and r["direction"] == expected["direction"]
            for r in exact_rows
        )

def test_master_import_keeps_direction():
    html = load_html("04_sunrelius_kokura_ekiminami")

    mod = load_target_module()
    extractor = resolve_extractor(mod)
    mapper = resolve_master_mapper(mod)

    rows = extractor(html)
    master_rows = mapper(rows)

    non_mosaic = [r for r in master_rows if not r.get("is_mosaic")]
    assert len(non_mosaic) > 0

    for row in non_mosaic:
        assert row.get("direction", "") not in ("", None)

def test_master_import_does_not_backfill_mosaic():
    html = load_html("02_sunpark_kokura_tower_residence")

    mod = load_target_module()
    extractor = resolve_extractor(mod)
    mapper = resolve_master_mapper(mod)

    rows = extractor(html)
    master_rows = mapper(rows)

    assert len(master_rows) == 3

    for row in master_rows:
        assert row.get("is_mosaic") is True
        assert row.get("area_sqm", "") in ("", None)
        assert row.get("layout", "") in ("", None)
        assert row.get("floor", "") in ("", None)
        assert row.get("direction", "") in ("", None)

