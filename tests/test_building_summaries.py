from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.normalize.building_summaries import rebuild


def test_summary_ranges(tmp_path):
    db = tmp_path / "test.sqlite3"
    conn = connect(db)
    upsert_listing(conn, ListingRecord("Aマンション", "東京都A", 50000, 20.0, "1K", "2026-01-01", "ulucks", "u1", move_in_date="即入居"))
    upsert_listing(conn, ListingRecord("Aマンション", "東京都A", 70000, 30.0, "1LDK", "2026-01-02", "ulucks", "u2", move_in_date="2026-02-01"))
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

    assert "即入居" in row["move_in_dates_json"]


def test_summary_age_years_and_structure_aggregation_rules(tmp_path):
    db = tmp_path / "test2.sqlite3"
    conn = connect(db)
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')")
    conn.executemany(
        """
        INSERT INTO listings(listing_key, building_key, name, address, room_label, rent_yen, maint_yen, layout, area_sqm, move_in_date, age_years, structure, updated_at, source_kind, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("l1", "b1", "Aマンション", "東京都A", "101", 50000, 0, "1K", 20.0, None, 10, "RC", "2026-01-01", "master", "s1"),
            ("l2", "b1", "Aマンション", "東京都A", "102", 52000, 0, "1K", 21.0, None, 12, "S", "2026-01-02", "master", "s2"),
            ("l3", "b1", "Aマンション", "東京都A", "103", 54000, 0, "1DK", 22.0, None, 10, "RC", "2026-01-03", "master", "s3"),
            ("l4", "b1", "Aマンション", "東京都A", "104", 56000, 0, "1DK", 23.0, None, 12, "SRC", "2026-01-04", "master", "s4"),
        ],
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    row = conn.execute("SELECT age_years, structure FROM building_summaries WHERE building_key='b1'").fetchone()
    conn.close()

    assert row["age_years"] == 11
    assert row["structure"] == "RC"
