from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.normalize.building_summaries import rebuild


def test_summary_ranges(tmp_path):
    db = tmp_path / "test.sqlite3"
    conn = connect(db)
    upsert_listing(conn, ListingRecord("Aマンション", "東京都A", 50000, 20.0, "1K", "2026-01-01", "ulucks", "u1"))
    upsert_listing(conn, ListingRecord("Aマンション", "東京都A", 70000, 30.0, "1LDK", "2026-01-02", "ulucks", "u2"))
    conn.close()

    rebuild(str(db))
    conn = connect(db)
    row = conn.execute("SELECT * FROM building_summaries").fetchone()
    assert row["rent_yen_min"] == 50000
    assert row["rent_yen_max"] == 70000
    assert row["area_sqm_min"] == 20.0
    assert row["area_sqm_max"] == 30.0
    assert row["layout_types_json"]
    assert row["last_updated"] == "2026-01-02"
