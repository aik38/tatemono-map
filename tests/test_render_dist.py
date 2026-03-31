import json
from pathlib import Path

import pytest

from tatemono_map.db.keys import make_building_key
from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.render.build import build_dist, build_dist_versions
from tatemono_map.render.build import _sort_area_buildings


def _pick_primary_detail_path(detail_dir: Path) -> Path:
    pages = sorted(detail_dir.glob("*.html"))
    assert pages
    for page in pages:
        if "-" in page.stem:
            return page
    return pages[0]


def test_render_dist_outputs(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("Bマンション", "東京都B", 55000, 22.0, "1K", "2026-01-01", "ulucks", "u1", move_in_date="即入居"),
    )
    conn.close()
    rebuild(str(db))
    build_dist(str(db), str(dist))

    index = (dist / "index.html").read_text(encoding="utf-8")
    assert "建物名・住所で絞り込み" in index
    page = _pick_primary_detail_path(dist / "b").read_text(encoding="utf-8")
    assert "Googleマップを開く" in page
    assert "号室" not in page
    assert "source_url" not in page
    assert "築年数" in page
    assert "構造" in page
    assert "最終更新日時" not in page


def test_render_dist_sanitizes_room_number_from_name_and_address(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord(
            "サンプルレジデンス 401号室",
            "東京都渋谷区神南1-2-3 401号室",
            120000,
            35.0,
            "1LDK",
            "2026-02-01",
            "ulucks",
            "u2",
        ),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist))

    index = (dist / "index.html").read_text(encoding="utf-8")
    assert "号室" not in index
    assert "サンプルレジデンス" in index
    assert "東京都渋谷区神南1-2-3" in index

    detail = _pick_primary_detail_path(dist / "b").read_text(encoding="utf-8")
    assert "号室" not in detail


def test_render_dist_creates_nojekyll_file(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("ノージキル確認マンション", "東京都港区1-2-3", 98000, 26.0, "1K", "2026-03-01", "ulucks", "u3"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist))

    assert (dist / ".nojekyll").exists()


def test_render_dist_writes_legacy_detail_redirect_stub(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("旧URL検証マンション", "福岡県北九州市小倉北区", 98000, 26.0, "1K", "2026-03-01", "ulucks", "legacy-stub"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    detail_page = _pick_primary_detail_path(dist / "b")
    legacy_page = next(page for page in sorted((dist / "b").glob("*.html")) if page.stem == detail_page.stem.split("-")[-1])
    legacy_html = legacy_page.read_text(encoding="utf-8")
    assert '<meta http-equiv="refresh"' in legacy_html
    assert "window.location.replace(" in legacy_html
    assert 'rel="canonical" href="https://www.tatemono-map.com/b/' in legacy_html


def test_render_dist_fails_when_forbidden_text_exists(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("管理会社掲載マンション", "東京都B", 55000, 22.0, "1K", "2026-01-01", "ulucks", "u1"),
    )
    conn.close()
    rebuild(str(db))

    with pytest.raises(RuntimeError):
        build_dist(str(db), str(dist))


def test_build_dist_versions_outputs_v1_and_v2(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("デュアル出力マンション", "東京都千代田区1-2-3", 100000, 30.0, "1LDK", "2026-04-01", "ulucks", "dual"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    assert (out / "index.html").exists()
    assert list((out / "b").glob("*.html"))
    assert (out / "v1" / "index.html").exists()
    assert list((out / "v1" / "b").glob("*.html"))


def test_v2_line_cta_is_single_button_with_deeplink_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("TATEMONO_MAP_LINE_CTA_URL", "https://line.example/universal")
    monkeypatch.setenv("TATEMONO_MAP_LINE_DEEP_LINK_URL", "line://ti/p/@example")

    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("LINE確認マンション", "東京都新宿区1-1-1", 99000, 28.0, "1DK", "2026-06-01", "ulucks", "line-check"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    page = _pick_primary_detail_path(out / "b").read_text(encoding="utf-8")

    # CTA section has only one button anchor.
    assert page.count('class="button button--line"') == 1
    assert 'href="https://line.example/universal"' in page
    assert 'data-line-universal-url="https://line.example/universal"' in page
    assert 'data-line-deep-link="line://ti/p/@example"' in page
    assert "setTimeout(function(){window.location.href=fallback;},700);" in page


def test_render_dist_formats_rent_with_thousands_separator(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("カンマ確認マンション", "東京都品川区1-2-3", 123000, 40.0, "2DK", "2026-05-01", "ulucks", "comma"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist))

    index = (dist / "index.html").read_text(encoding="utf-8")
    detail = _pick_primary_detail_path(dist / "b").read_text(encoding="utf-8")

    assert "123,000円" in index
    assert "123,000円" in detail


def test_build_dist_versions_formats_rent_with_thousands_separator_in_v1_and_v2(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("カンマ確認マンションv2", "東京都中央区1-2-3", 125000, 40.0, "2DK", "2026-05-01", "ulucks", "comma-v2"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v1 = (out / "v1" / "index.html").read_text(encoding="utf-8")
    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    detail_v1 = _pick_primary_detail_path(out / "v1" / "b").read_text(encoding="utf-8")
    detail_v2 = _pick_primary_detail_path(out / "b").read_text(encoding="utf-8")

    assert "125,000円" in index_v1
    assert "125,000円" in index_v2
    assert "125,000円" in detail_v1
    assert "125,000円" in detail_v2


def test_build_dist_versions_v2_index_has_search_label_and_top_kpis(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("カウント確認マンション", "福岡県北九州市小倉北区京町", 88000, 30.0, "1LDK", "2026-08-01", "ulucks", "counts"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    assert "建物名・住所で検索" in index_v2
    assert "<span>建物数</span>0件" in index_v2
    assert "<span>空部屋</span>0件" in index_v2
    assert "表示中" not in index_v2




def test_build_dist_versions_v2_index_search_update_pipeline(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("ハイツ門司", "福岡県北九州市門司区", 68000, 24.0, "1K", "2026-09-01", "ulucks", "pipeline-1"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    assert "function update()" in index_v2
    assert "const normalizeText" in index_v2
    assert "currentQuery = normalizeText(input.value)" in index_v2
    assert 'const shouldShowCounts = currentQuery !== "";' in index_v2
    assert "counts.hidden = !shouldShowCounts;" in index_v2
    assert "if (visibleCount.textContent !== nextVisible)" in index_v2
    assert "if (totalCount.textContent !== nextTotal)" in index_v2
    assert "if (vacantCount.textContent !== nextVacant)" in index_v2
    assert "visible.forEach((card) => {" in index_v2
    assert "list.appendChild(card.el)" in index_v2
    assert "input.addEventListener('change', update)" in index_v2




def test_build_dist_versions_v2_index_counts_container_has_cls_guard(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("プレースホルダ確認マンション", "福岡県北九州市小倉北区", 72000, 25.0, "1K", "2026-10-01", "ulucks", "placeholder-1"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    assert 'id="result-counts"' in index_v2
    assert '.counts { margin: -2px 0 14px; color: var(--muted); font-size: .92rem; white-space: nowrap; }' in index_v2


def test_build_dist_versions_v2_index_renders_counts_with_initial_values(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("初期件数A", "福岡県北九州市小倉北区", 70000, 25.0, "1K", "2026-11-01", "ulucks", "initial-a"),
    )
    upsert_listing(
        conn,
        ListingRecord("初期件数B", "福岡県北九州市門司区", 73000, 26.0, "1DK", "2026-11-02", "ulucks", "initial-b"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    assert 'id="result-count-visible">0件</strong>' in index_v2
    assert 'id="result-count-vacant">0件</strong>' in index_v2
    assert '.counts { margin: -2px 0 14px; color: var(--muted); font-size: .92rem; white-space: nowrap; }' in index_v2


def test_build_dist_versions_v2_index_has_multi_token_search_logic(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("門司サンプルマンション", "福岡県北九州市門司区", 78000, 28.0, "1DK", "2026-08-15", "ulucks", "rank-1"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    assert "const tokenizeQuery" in index_v2
    assert "function matchesTokens" in index_v2
    assert "function compareCards" in index_v2
    assert "tokens.every" in index_v2
    assert "b.score - a.score" not in index_v2


def test_build_dist_versions_outputs_v2_min_json_with_contract(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("min契約確認マンション", "東京都目黒区1-2-3", 112000, 31.5, "1LDK", "2026-11-01", "ulucks", "min-contract"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    min_path = out / "data" / "buildings.v2.min.json"
    assert min_path.exists()
    payload = json.loads(min_path.read_text(encoding="utf-8"))
    assert payload

    required_keys = {
        "id",
        "detail_filename",
        "name",
        "address",
        "vacancy_count",
        "rent_min",
        "rent_max",
        "sale_price_min",
        "sale_price_max",
        "sale_price_avg",
        "area_min",
        "area_max",
        "sale_area_min",
        "sale_area_max",
        "updated_at",
        "updated_epoch",
        "property_kind",
        "sale_listing_count",
        "building_structure",
        "building_availability_label",
        "building_built_year_month",
        "building_built_age_years",
    }
    disallowed = {"google_maps_url", "room_types", "structure", "built_year"}

    for item in payload[:3]:
        assert required_keys.issubset(item.keys())
        assert not (set(item.keys()) & disallowed)
        assert set(item.keys()) == required_keys




def test_build_dist_versions_v2_index_uses_relative_data_paths(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("相対パス確認マンション", "東京都目黒区1-2-3", 121000, 31.0, "1LDK", "2027-01-01", "ulucks", "relative-paths"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    assert "./data/buildings.v2.min.json" in index_v2
    assert "./data/buildings.json" in index_v2
    assert "'/data/" not in index_v2
    assert '"/data/' not in index_v2

def test_build_dist_versions_v2_index_has_min_json_fallback_logic(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("fallback確認マンション", "東京都世田谷区1-2-3", 118000, 33.0, "1LDK", "2026-12-01", "ulucks", "min-fallback"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    assert "./data/buildings.v2.min.json" in index_v2
    assert "./data/buildings.json" in index_v2
    assert "function loadBuildingsWithFallback()" in index_v2
    assert "function validateRawItems(raw, sourceLabel)" in index_v2


def test_render_dist_versions_detail_shows_immediate_when_availability_label_is_nyukyo(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("即入居表示マンション", "東京都港区2-3-4", 101000, 29.0, "1DK", "2026-04-01", "ulucks", "imm-1"),
    )
    conn.execute(
        """
        UPDATE listings
        SET move_in_date = '', availability_raw = '', availability_flag_immediate = 1
        WHERE source_url = 'imm-1'
        """
    )
    conn.commit()
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    detail_v2 = _pick_primary_detail_path(out / "b").read_text(encoding="utf-8")
    detail_v1 = _pick_primary_detail_path(out / "v1" / "b").read_text(encoding="utf-8")

    assert "<dt>入居可能日</dt><dd>即入居</dd>" in detail_v2
    assert "<dt>入居可能日</dt>" in detail_v1
    assert "即入居" in detail_v1


def test_render_dist_versions_detail_uses_building_availability_label_when_present(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("ラベル優先マンション", "東京都港区5-6-7", 111000, 30.0, "1LDK", "2026-05-01", "realpro", "label-1"),
    )
    conn.execute(
        """
        UPDATE listings
        SET move_in_date = '', availability_raw = '退去予定', availability_flag_immediate = 0
        WHERE source_url = 'label-1'
        """
    )
    conn.commit()
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    detail_v2 = _pick_primary_detail_path(out / "b").read_text(encoding="utf-8")
    assert "<dt>入居可能日</dt><dd>退去予定</dd>" in detail_v2

def test_export_buildings_json_not_empty_and_required_keys(tmp_path):
    from tatemono_map.render.build import export_buildings_json

    db = tmp_path / "test.sqlite3"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("JSON出力確認マンション", "東京都港区芝公園1-2-3", 101000, 29.0, "1DK", "2026-11-01", "ulucks", "json-check"),
    )
    conn.close()

    rebuild(str(db))
    out = tmp_path / "dist" / "data" / "buildings.v2.min.json"
    count = export_buildings_json(str(db), str(out), "v2min")

    assert count > 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload

    row = payload[0]
    assert "id" in row
    assert "name" in row
    assert "address" in row
    assert "vacancy_count" in row


def test_build_dist_versions_outputs_build_info_json(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("build_info確認マンション", "福岡県北九州市小倉北区浅野1-1-1", 89000, 26.0, "1K", "2026-12-01", "ulucks", "build-info"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    build_info = json.loads((out / "build_info.json").read_text(encoding="utf-8"))
    assert build_info["buildings_count_json"] > 0
    assert build_info["buildings_count_db"] >= 0
    assert "generated_at" in build_info
    assert "git_sha" in build_info


def test_build_dist_versions_theme_init_and_theme_variables_present(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("テーマ確認マンション", "福岡県北九州市小倉北区", 84000, 29.0, "1LDK", "2027-02-01", "ulucks", "theme-check"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    detail_v2 = _pick_primary_detail_path(out / "b").read_text(encoding="utf-8")

    for html in (index_v2, detail_v2):
        assert 'new Set(["default", "ph", "mercari"])' in html
        assert 'const theme = allowed.has(q) ? q : "ph";' in html
        assert 'localStorage.setItem("tm_theme", theme)' in html
        assert 'root.classList.remove("theme-ph", "theme-mercari")' in html
        assert 'if (theme === "ph") root.classList.add("theme-ph")' in html
        assert 'if (theme === "mercari") root.classList.add("theme-mercari")' in html
        assert 'html.theme-ph' in html
        assert 'html.theme-mercari' in html



def test_build_dist_versions_define_control_tokens_and_apply_form_text_color(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("コントロール配色確認", "東京都台東区1-2-3", 93000, 28.0, "1DK", "2026-12-01", "ulucks", "control-theme"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v1 = (out / "v1" / "index.html").read_text(encoding="utf-8")
    index_v2 = (out / "index.html").read_text(encoding="utf-8")

    for html in (index_v1, index_v2):
        assert "--control-bg" in html
        assert "--control-text" in html
        assert "--control-placeholder" in html
        assert "--control-border" in html
        assert "--control-focus-ring" in html
        assert "--control-icon" in html
        assert "html.theme-ph" in html and "--control-text: #f4f4f4;" in html
        assert "html.theme-mercari" in html and "--control-text: #222222;" in html
        assert "input," in html
        assert "select," in html
        assert "textarea" in html
        assert "color: var(--control-text);" in html

    assert ".button-secondary" in index_v2
    assert "border: 1px solid var(--control-border); background: var(--control-bg); color: var(--control-text);" in index_v2
    assert ".button-secondary:focus-visible" in index_v2 and "box-shadow: 0 0 0 3px var(--control-focus-ring);" in index_v2


def test_build_dist_versions_v2_index_applies_user_sort_without_relevance_override(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("砂津テストマンション", "福岡県北九州市小倉北区砂津", 78000, 25.0, "1K", "2026-11-01", "ulucks", "sort-guard"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    assert "function compareCards(a, b, q, sorter)" in index_v2
    assert "b.score - a.score" not in index_v2
    assert "const compareBuiltAgeAsc = (a, b) => {" in index_v2
    assert "const bucketDiff = builtAgeBucket(a) - builtAgeBucket(b);" in index_v2
    assert "const ymDiff = b.builtYmSort - a.builtYmSort;" in index_v2
    assert "const kindDiff = propertyKindRank(a) - propertyKindRank(b);" in index_v2
    assert "const ageDiff = compareWithUnknownLast(a, b, 'builtAgeSort', 'asc');" in index_v2
    assert "const builtAgeKnown = knownNumberOrNull(item.building_built_age_years);" in index_v2
    assert "const builtYmSort = parseBuiltYm(item.building_built_year_month);" in index_v2
    assert "const isFutureBuilt = builtYmSort !== null && builtYmSort > currentYm;" in index_v2
    assert "built_age_asc: compareBuiltAgeAsc" in index_v2
    assert "calcAgeYearsFromBuiltYearMonth" not in index_v2


def test_sort_area_buildings_defaults_to_base_score_when_popularity_missing():
    rows = [
        {
            "building_key": "old-full",
            "updated_epoch": 1_700_000_000,
            "vacancy_count": 2,
            "rent_yen_min": 70000,
            "rent_yen_max": 80000,
            "area_sqm_min": 20,
            "area_sqm_max": 30,
            "structure": "RC",
            "property_kind": "chintai",
        },
        {
            "building_key": "new-empty",
            "updated_epoch": 1_700_100_000,
            "vacancy_count": 0,
            "rent_yen_min": None,
            "rent_yen_max": None,
            "area_sqm_min": None,
            "area_sqm_max": None,
            "structure": None,
            "property_kind": "",
        },
    ]

    sorted_rows = _sort_area_buildings(rows)

    assert [row["building_key"] for row in sorted_rows] == ["old-full", "new-empty"]


def test_sort_area_buildings_accepts_popularity_score_and_ignores_invalid_values():
    rows = [
        {
            "building_key": "base-top",
            "updated_epoch": 1_700_000_000,
            "vacancy_count": 3,
            "rent_yen_min": 70000,
            "rent_yen_max": 80000,
            "area_sqm_min": 20,
            "area_sqm_max": 30,
            "structure": "RC",
            "property_kind": "chintai",
            "popularity_score": "not-a-number",
        },
        {
            "building_key": "popular",
            "updated_epoch": 1_699_900_000,
            "vacancy_count": 1,
            "rent_yen_min": 70000,
            "rent_yen_max": 80000,
            "area_sqm_min": 20,
            "area_sqm_max": 30,
            "structure": "RC",
            "property_kind": "chintai",
            "popularity_score": 1000,
        },
    ]

    sorted_rows = _sort_area_buildings(rows)

    assert [row["building_key"] for row in sorted_rows] == ["popular", "base-top"]


def test_built_age_asc_priority_rules_and_relevance_override_guard():
    def compare_with_unknown_last(a, b, key):
        av = a.get(key)
        bv = b.get(key)
        a_unknown = av is None
        b_unknown = bv is None
        if a_unknown and b_unknown:
            return 0
        if a_unknown:
            return 1
        if b_unknown:
            return -1
        return av - bv

    def bucket(item, now_ym):
        ym = item.get("builtYmSort")
        if ym is None:
            return 3
        if ym > now_ym:
            return 0
        if item.get("builtAgeSort") == 0:
            return 1
        return 2

    def kind_rank(item):
        kind = item.get("propertyKind")
        if kind == "chintai":
            return 0
        if kind == "bunjo":
            return 1
        return 2

    def cmp(a, b, now_ym=2025 * 12 + 2):
        bucket_diff = bucket(a, now_ym) - bucket(b, now_ym)
        if bucket_diff != 0:
            return bucket_diff
        if a.get("builtYmSort") is not None and b.get("builtYmSort") is not None:
            ym_diff = b["builtYmSort"] - a["builtYmSort"]
            if ym_diff != 0:
                return ym_diff
            kind_diff = kind_rank(a) - kind_rank(b)
            if kind_diff != 0:
                return kind_diff
        age_diff = compare_with_unknown_last(a, b, "builtAgeSort")
        if age_diff != 0:
            return age_diff
        return 0

    unknown = {"builtYmSort": None, "builtAgeSort": None, "propertyKind": "bunjo", "score": 999}
    zero_year = {"builtYmSort": 2025 * 12 + 2, "builtAgeSort": 0, "propertyKind": "bunjo", "score": 0}
    future = {"builtYmSort": 2025 * 12 + 3, "builtAgeSort": 0, "propertyKind": "bunjo", "score": 0}
    y202503_bunjo = {"builtYmSort": 2025 * 12 + 3, "builtAgeSort": 0, "propertyKind": "bunjo", "score": 0}
    y202503_chintai = {"builtYmSort": 2025 * 12 + 3, "builtAgeSort": 0, "propertyKind": "chintai", "score": 0}
    y202502_chintai = {"builtYmSort": 2025 * 12 + 2, "builtAgeSort": 0, "propertyKind": "chintai", "score": 0}
    y202501_bunjo = {"builtYmSort": 2025 * 12 + 1, "builtAgeSort": 0, "propertyKind": "bunjo", "score": 0}

    # 1. unknown built age は 0年より下
    assert cmp(unknown, zero_year) > 0
    # 2. unknown built age は future より下
    assert cmp(unknown, future) > 0
    # 3. 2025-03 は 2025-01 より上（築浅順）
    assert cmp(y202503_bunjo, y202501_bunjo) < 0
    # 4. 2025-03 の bunjo より 2025-03 の chintai が上
    assert cmp(y202503_chintai, y202503_bunjo) < 0
    # 5. 2025-03 の bunjo は 2025-02 の chintai より上
    assert cmp(y202503_bunjo, y202502_chintai) < 0
    # 6. relevance が built_age_asc を上書きしない（scoreは比較に影響しない）
    high_score_unknown = dict(unknown, score=10_000)
    assert cmp(high_score_unknown, zero_year) > 0


def test_export_buildings_json_excludes_hidden_from_public(tmp_path):
    from tatemono_map.render.build import export_buildings_json

    db = tmp_path / "test.sqlite3"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("公開建物", "東京都港区芝1-1-1", 100000, 30.0, "1DK", "2026-11-01", "ulucks", "json-visible"),
    )
    upsert_listing(
        conn,
        ListingRecord("除外建物", "東京都港区芝1-1-2", 120000, 33.0, "1LDK", "2026-11-01", "ulucks", "json-hidden"),
    )
    hidden_key = make_building_key("除外建物", "東京都港区芝1-1-2")
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address, hidden_from_public)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(building_id) DO UPDATE SET hidden_from_public=1
        """,
        (hidden_key, "除外建物", "東京都港区芝1-1-2", "除外建物", "東京都港区芝1-1-2"),
    )
    conn.commit()
    conn.close()

    rebuild(str(db))
    out = tmp_path / "dist" / "data" / "buildings.v2.min.json"
    export_buildings_json(str(db), str(out), "v2min")

    payload = json.loads(out.read_text(encoding="utf-8"))
    names = {row["name"] for row in payload}
    assert "公開建物" in names
    assert "除外建物" not in names


def test_render_dist_base_path_applies_to_favicon_and_manifest(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("BASE_PATH確認マンション", "東京都港区1-2-3", 110000, 33.0, "1LDK", "2026-10-01", "ulucks", "base-path"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="/tatemono-map")

    index = (dist / "index.html").read_text(encoding="utf-8")
    detail = _pick_primary_detail_path(dist / "b").read_text(encoding="utf-8")
    manifest = json.loads((dist / "assets" / "favicon" / "site.webmanifest").read_text(encoding="utf-8"))

    assert 'href="/tatemono-map/assets/favicon/favicon.png"' in index
    assert 'href="/tatemono-map/assets/favicon/site.webmanifest"' in index
    assert 'href="/tatemono-map/assets/favicon/favicon.png"' in detail
    assert 'href="/tatemono-map/assets/favicon/site.webmanifest"' in detail
    assert manifest["start_url"] == "/tatemono-map/"
    assert manifest["icons"][0]["src"] == "/tatemono-map/assets/favicon/favicon-192.png"
    assert manifest["icons"][1]["src"] == "/tatemono-map/assets/favicon/favicon-512.png"


def test_render_dist_empty_base_path_applies_to_favicon_and_manifest(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("BASE_PATH空確認マンション", "東京都港区3-2-1", 111000, 34.0, "1LDK", "2026-11-01", "ulucks", "base-path-root"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    index = (dist / "index.html").read_text(encoding="utf-8")
    detail = _pick_primary_detail_path(dist / "b").read_text(encoding="utf-8")
    manifest = json.loads((dist / "assets" / "favicon" / "site.webmanifest").read_text(encoding="utf-8"))

    assert 'href="/assets/favicon/favicon.png"' in index
    assert 'href="/assets/favicon/site.webmanifest"' in index
    assert 'href="/assets/favicon/favicon.png"' in detail
    assert 'href="/assets/favicon/site.webmanifest"' in detail
    assert "/tatemono-map/assets/favicon" not in index
    assert "/tatemono-map/assets/favicon" not in detail
    assert manifest["start_url"] == "/"
    assert manifest["icons"][0]["src"] == "/assets/favicon/favicon-192.png"
    assert manifest["icons"][1]["src"] == "/assets/favicon/favicon-512.png"


def test_render_dist_generates_root_mode_sitemap_with_canonical_urls(tmp_path, monkeypatch):
    monkeypatch.delenv("TATEMONO_MAP_SITE_ORIGIN", raising=False)
    monkeypatch.setenv("TATEMONO_MAP_SITE_URL", "https://www.tatemono-map.com")

    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("サイトマップ確認マンション", "福岡県北九州市小倉北区京町1-1-1", 83000, 31.0, "1LDK", "2026-11-01", "ulucks", "sitemap-root"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    detail_path = _pick_primary_detail_path(dist / "b")
    expected_detail_url = f"https://www.tatemono-map.com/b/{detail_path.stem}.html"

    sitemap = (dist / "sitemap.xml").read_text(encoding="utf-8")
    assert sitemap.startswith("<?xml version=\"1.0\" encoding=\"UTF-8\"?>")
    assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in sitemap
    assert "<loc>https://www.tatemono-map.com/</loc>" in sitemap
    assert f"<loc>{expected_detail_url}</loc>" in sitemap
    assert "?theme=" not in sitemap
    assert "/tatemono-map/" not in sitemap


def test_render_dist_generates_project_pages_mode_sitemap_with_base_path(tmp_path, monkeypatch):
    monkeypatch.setenv("TATEMONO_MAP_SITE_ORIGIN", "https://aik38.github.io")

    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("サイトマップ確認マンションPP", "福岡県北九州市小倉北区京町2-2-2", 84000, 32.0, "1LDK", "2026-11-01", "ulucks", "sitemap-pages"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="/tatemono-map")

    detail_path = _pick_primary_detail_path(dist / "b")
    expected_detail_url = f"https://aik38.github.io/tatemono-map/b/{detail_path.stem}.html"

    sitemap = (dist / "sitemap.xml").read_text(encoding="utf-8")
    assert "<loc>https://aik38.github.io/tatemono-map/</loc>" in sitemap
    assert f"<loc>{expected_detail_url}</loc>" in sitemap
    assert "?theme=" not in sitemap


def test_render_dist_generates_robots_txt_with_site_sitemap_url(tmp_path, monkeypatch):
    monkeypatch.setenv("TATEMONO_MAP_SITE_ORIGIN", "https://www.tatemono-map.com")

    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("robots確認マンション", "福岡県北九州市小倉北区京町3-3-3", 85000, 30.0, "1LDK", "2026-11-01", "ulucks", "robots-root"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    robots = (dist / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots
    assert "Allow: /" in robots
    assert "Sitemap: https://www.tatemono-map.com/sitemap.xml" in robots


def test_render_dist_v2_index_contains_static_building_links_in_initial_html(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    first_key = make_building_key("静的リンク確認マンションA", "福岡県北九州市小倉北区浅野1-1-1")
    second_key = make_building_key("静的リンク確認マンションB", "福岡県北九州市小倉北区浅野1-1-2")
    upsert_listing(
        conn,
        ListingRecord("静的リンク確認マンションA", "福岡県北九州市小倉北区浅野1-1-1", 86000, 31.0, "1LDK", "2026-11-01", "ulucks", "static-link-a"),
    )
    upsert_listing(
        conn,
        ListingRecord("静的リンク確認マンションB", "福岡県北九州市小倉北区浅野1-1-2", 87000, 32.0, "1LDK", "2026-11-01", "ulucks", "static-link-b"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    index = (dist / "index.html").read_text(encoding="utf-8")
    assert "建物マップ" in index
    assert f"-{first_key}.html" in index
    assert f"-{second_key}.html" in index


def test_build_dist_versions_includes_google_site_verification_meta(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("検証メタ確認マンション", "東京都台東区1-2-3", 87000, 23.0, "1K", "2026-11-01", "ulucks", "meta-check"),
    )
    conn.close()

    rebuild(str(db))
    build_dist_versions(str(db), str(out))

    expected = '<meta name="google-site-verification" content="JCW5x0Dh0VamrnKUfDq10VrBt27IDc0ceuWccjjpaUo">'
    index_v2 = (out / "index.html").read_text(encoding="utf-8")
    detail_v2 = _pick_primary_detail_path(out / "b").read_text(encoding="utf-8")

    assert expected in index_v2
    assert expected in detail_v2
    assert index_v2.index(expected) < index_v2.index("</head>")
    assert detail_v2.index(expected) < detail_v2.index("</head>")


def test_render_dist_includes_seo_meta_on_index_and_building_pages(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("プレジデンスざ三萩野", "福岡県北九州市小倉北区黄金1-2-10", 67000, 34.07, "1LDK", "2026-11-01", "ulucks", "seo-1"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="/tatemono-map")

    index = (dist / "index.html").read_text(encoding="utf-8")
    detail = _pick_primary_detail_path(dist / "b").read_text(encoding="utf-8")

    assert "<title>北九州の賃貸・建物データベース | 建物マップ</title>" in index
    assert 'name="description" content="北九州のマンション・アパートを建物単位で検索できる建物データベース。建物名、住所、空室数、家賃帯、面積帯などをまとめて確認できます。"' in index
    assert 'rel="canonical" href="https://www.tatemono-map.com/tatemono-map/"' in index

    assert "プレジデンスざ三萩野 | 小倉北区の建物情報 | 建物マップ" in detail
    assert 'name="description" content="プレジデンスざ三萩野は福岡県北九州市小倉北区黄金1-2-10にある建物です。' in detail
    assert 'rel="canonical" href="https://www.tatemono-map.com/tatemono-map/b/' in detail


def test_render_dist_building_description_handles_missing_values(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("欠損確認マンション", "福岡県北九州市門司区", None, None, None, "2026-11-01", "ulucks", "seo-missing"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2")

    detail = _pick_primary_detail_path(dist / "b").read_text(encoding="utf-8")

    assert 'name="description" content="欠損確認マンションは福岡県北九州市門司区にある建物です。' in detail
    assert "、、" not in detail
    assert "〜、" not in detail


def test_render_dist_root_mode_canonical_for_custom_domain(tmp_path, monkeypatch):
    monkeypatch.delenv("TATEMONO_MAP_SITE_ORIGIN", raising=False)
    monkeypatch.setenv("TATEMONO_MAP_SITE_URL", "https://www.tatemono-map.com")

    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("ルート配信確認マンション", "福岡県北九州市小倉北区京町1-1-1", 83000, 31.0, "1LDK", "2026-11-01", "ulucks", "root-canonical"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    index = (dist / "index.html").read_text(encoding="utf-8")
    detail_path = _pick_primary_detail_path(dist / "b")
    detail = detail_path.read_text(encoding="utf-8")

    assert 'rel="canonical" href="https://www.tatemono-map.com/"' in index
    assert 'rel="canonical" href="https://www.tatemono-map.com/b/' in detail
    assert "/tatemono-map/" not in "\n".join(line for line in index.splitlines() if "canonical" in line)
    assert "/tatemono-map/" not in "\n".join(line for line in detail.splitlines() if "canonical" in line)
    assert "?" not in "\n".join(line for line in index.splitlines() if "canonical" in line)
    assert "?" not in "\n".join(line for line in detail.splitlines() if "canonical" in line)
    assert index.index('rel="canonical"') < index.index("</head>")
    assert detail.index('rel="canonical"') < detail.index("</head>")
    assert '<meta name="google-site-verification" content="JCW5x0Dh0VamrnKUfDq10VrBt27IDc0ceuWccjjpaUo">' in index
    assert '<meta name="google-site-verification" content="JCW5x0Dh0VamrnKUfDq10VrBt27IDc0ceuWccjjpaUo">' in detail


def test_render_dist_generates_area_hub_pages_for_non_kokurakita_areas(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("苅田町確認マンション", "福岡県京都郡苅田町神田町1-1-1", 79000, 29.0, "1LDK", "2026-11-01", "ulucks", "karita-hub"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    index = (dist / "index.html").read_text(encoding="utf-8")
    area_page = (dist / "area" / "fukuoka" / "keichiku" / "miyako-gun" / "index.html").read_text(encoding="utf-8")

    assert "/area/fukuoka/keichiku/miyako-gun/" in index
    assert "京都郡の建物一覧・住所・募集情報 | 建物マップ" in area_page
    assert "苅田町確認マンション" in area_page


def test_render_dist_related_buildings_excludes_tagawa_for_karita(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("苅田町ターゲット", "福岡県京都郡苅田町幸町1-1-1", 81000, 30.0, "1LDK", "2026-11-01", "ulucks", "karita-target"),
    )
    upsert_listing(
        conn,
        ListingRecord("苅田町関連", "福岡県京都郡苅田町京町2-2-2", 82000, 31.0, "1LDK", "2026-11-01", "ulucks", "karita-related"),
    )
    upsert_listing(
        conn,
        ListingRecord("田川市ノイズ", "福岡県田川市本町3-3-3", 65000, 28.0, "1K", "2026-11-01", "ulucks", "tagawa-noise"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    detail = next(
        page.read_text(encoding="utf-8")
        for page in (dist / "b").glob("*.html")
        if "-" in page.stem
        and "苅田町ターゲット" in page.read_text(encoding="utf-8")
        and "window.location.replace(" not in page.read_text(encoding="utf-8")
    )
    assert "同じエリアの建物" in detail
    assert "苅田町関連" in detail
    assert "田川市ノイズ" not in detail




def test_render_dist_related_buildings_prioritizes_same_town_then_fills_same_ward(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("浅野ターゲット", "福岡県北九州市小倉北区浅野2-1-1", 83000, 31.0, "1LDK", "2026-11-01", "ulucks", "asano-target"),
    )
    upsert_listing(
        conn,
        ListingRecord("浅野関連", "福岡県北九州市小倉北区浅野1-2-3", 82000, 30.0, "1LDK", "2026-10-01", "ulucks", "asano-related"),
    )
    upsert_listing(
        conn,
        ListingRecord("京町補完", "福岡県北九州市小倉北区京町9-9-9", 84000, 32.0, "1LDK", "2026-12-01", "ulucks", "kyomachi-fill"),
    )
    upsert_listing(
        conn,
        ListingRecord("小倉南ノイズ2", "福岡県北九州市小倉南区守恒3-3-3", 76000, 30.0, "1LDK", "2026-11-01", "ulucks", "kokuraminami-noise-2"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    detail = next(
        page.read_text(encoding="utf-8")
        for page in (dist / "b").glob("*.html")
        if "浅野ターゲット" in page.read_text(encoding="utf-8") and "window.location.replace(" not in page.read_text(encoding="utf-8")
    )

    assert "浅野関連" in detail
    assert "京町補完" in detail
    assert "小倉南ノイズ2" not in detail
    assert detail.index("浅野関連") < detail.index("京町補完")


def test_render_dist_related_buildings_falls_back_to_same_ward_when_town_missing(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("町名なしターゲット", "福岡県北九州市小倉北区", 83000, 31.0, "1LDK", "2026-11-01", "ulucks", "no-town-target"),
    )
    upsert_listing(
        conn,
        ListingRecord("同区関連", "福岡県北九州市小倉北区京町2-2-2", 84000, 32.0, "1LDK", "2026-11-01", "ulucks", "same-ward-related"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    detail = next(
        page.read_text(encoding="utf-8")
        for page in (dist / "b").glob("*.html")
        if "町名なしターゲット" in page.read_text(encoding="utf-8") and "window.location.replace(" not in page.read_text(encoding="utf-8")
    )
    assert "同区関連" in detail

def test_render_dist_related_buildings_keeps_existing_kitakyushu_behavior(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("小倉北ターゲット", "福岡県北九州市小倉北区魚町1-1-1", 83000, 31.0, "1LDK", "2026-11-01", "ulucks", "kokurakita-target"),
    )
    upsert_listing(
        conn,
        ListingRecord("小倉北関連", "福岡県北九州市小倉北区京町2-2-2", 84000, 32.0, "1LDK", "2026-11-01", "ulucks", "kokurakita-related"),
    )
    upsert_listing(
        conn,
        ListingRecord("小倉南ノイズ", "福岡県北九州市小倉南区守恒3-3-3", 76000, 30.0, "1LDK", "2026-11-01", "ulucks", "kokuraminami-noise"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(dist), template_root="templates_v2", base_path="")

    detail = next(
        page.read_text(encoding="utf-8")
        for page in (dist / "b").glob("*.html")
        if "-" in page.stem and "小倉北ターゲット" in page.stem
    )
    assert "小倉北関連" in detail
    assert "小倉南ノイズ" not in detail
