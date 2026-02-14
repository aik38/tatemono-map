import os
import subprocess
import sys

from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.render.build import build_dist


def test_build_generates_index_and_building_pages(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("スモークマンション", "東京都千代田区1-1", 82000, 25.0, "1K", "2026-01-01", "smartlink_page", "u1"),
    )
    conn.close()

    rebuild(str(db))
    build_dist(str(db), str(out))

    assert (out / "index.html").exists()
    pages = list((out / "b").glob("*.html"))
    assert pages


def test_cli_build_all_outputs_pages_layout_for_actions(tmp_path):
    db = tmp_path / "test.sqlite3"
    out = tmp_path / "dist"
    conn = connect(db)
    upsert_listing(
        conn,
        ListingRecord("CLI確認マンション", "東京都港区1-1", 91000, 27.5, "1K", "2026-07-01", "smartlink_page", "cli-check"),
    )
    conn.close()
    rebuild(str(db))

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    subprocess.run(
        [sys.executable, "-m", "tatemono_map.render.build", "--db-path", str(db), "--output-dir", str(out), "--version", "all"],
        check=True,
        env=env,
    )

    assert (out / "index.html").exists()
    assert list((out / "b").glob("*.html"))
    assert (out / "v1" / "index.html").exists()
