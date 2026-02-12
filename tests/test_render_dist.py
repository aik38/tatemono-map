from pathlib import Path

import pytest

from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.render.build import build_dist


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
