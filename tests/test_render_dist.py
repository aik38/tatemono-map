from pathlib import Path

from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.render.build import build_dist


def test_render_dist_outputs(tmp_path):
    db = tmp_path / "test.sqlite3"
    dist = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(conn, ListingRecord("Bマンション", "東京都B", 55000, 22.0, "1K", "2026-01-01", "ulucks", "u1"))
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
