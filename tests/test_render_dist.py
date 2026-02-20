from pathlib import Path

import pytest

from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.render.build import build_dist, build_dist_versions


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
    pages = list((dist / "b").glob("*.html"))
    assert pages
    page = pages[0].read_text(encoding="utf-8")
    assert "Googleマップを開く" in page
    assert "号室" not in page
    assert "source_url" not in page


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

    detail_pages = list((dist / "b").glob("*.html"))
    assert detail_pages
    detail = detail_pages[0].read_text(encoding="utf-8")
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

    page = next((out / "b").glob("*.html")).read_text(encoding="utf-8")

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
    detail = next((dist / "b").glob("*.html")).read_text(encoding="utf-8")

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
    detail_v1 = next((out / "v1" / "b").glob("*.html")).read_text(encoding="utf-8")
    detail_v2 = next((out / "b").glob("*.html")).read_text(encoding="utf-8")

    assert "125,000円" in index_v1
    assert "125,000円" in index_v2
    assert "125,000円" in detail_v1
    assert "125,000円" in detail_v2


def test_build_dist_versions_v2_index_has_search_label_and_counts(tmp_path):
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
    assert "表示中" in index_v2
    assert "建物" in index_v2
    assert "空室" in index_v2




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
    assert 'id="result-count-visible">2件</strong>' in index_v2
    assert 'id="result-count-vacant">2件</strong>' in index_v2
    assert '.counts { margin: -2px 0 14px; color: var(--muted); font-size: .92rem; white-space: nowrap; }' in index_v2


def test_build_dist_versions_v2_index_has_search_ranking_logic(tmp_path):
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
    assert "function getMatchScore" in index_v2
    assert "function compareCards" in index_v2
    assert "card.score === 0" in index_v2
    assert "b.score - a.score" in index_v2
