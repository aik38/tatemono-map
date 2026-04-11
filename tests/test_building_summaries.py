from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.util.building_age import age_years_from_built_year_month


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


def test_summary_building_availability_prefers_immediate(tmp_path):
    db = tmp_path / "test3.sqlite3"
    conn = connect(db)
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')")
    conn.executemany(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label, rent_yen, maint_yen, layout, area_sqm,
            move_in_date, age_years, structure, built_year_month, built_age_years,
            availability_raw, availability_date, availability_flag_immediate, structure_raw, updated_at, source_kind, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "l1",
                "b1",
                "Aマンション",
                "東京都A",
                "101",
                50000,
                0,
                "1K",
                20.0,
                "3/9",
                3,
                "RC",
                "2023-01",
                3,
                "退去予定",
                "2026-03-09",
                0,
                "RC",
                "2026-02-28",
                "master",
                "s1",
            ),
            (
                "l2",
                "b1",
                "Aマンション",
                "東京都A",
                "102",
                52000,
                0,
                "1K",
                21.0,
                "即入居",
                3,
                "RC",
                "2023-01",
                3,
                "",
                None,
                1,
                "RC",
                "2026-02-28",
                "master",
                "s2",
            ),
        ],
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    row = conn.execute(
        "SELECT building_availability_label, building_structure, building_built_year_month, building_built_age_years FROM building_summaries WHERE building_key='b1'"
    ).fetchone()
    conn.close()

    assert row["building_availability_label"] == "入居"
    assert row["building_structure"] == "RC"
    assert row["building_built_year_month"] == "2023-01"
    assert row["building_built_age_years"] == 3


def test_refresh_building_availability_labels_priority(tmp_path):
    db = tmp_path / "test4.sqlite3"
    conn = connect(db)
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')")
    conn.executemany(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            availability_raw, updated_at, source_kind, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("l1", "b1", "Aマンション", "東京都A", "101", 50000, 0, "1K", 20.0, None, "退去予定 4月下旬", "2026-01-01", "master", "s1"),
            ("l2", "b1", "Aマンション", "東京都A", "102", 51000, 0, "1K", 20.5, None, "空室", "2026-01-02", "master", "s2"),
            ("l3", "b1", "Aマンション", "東京都A", "103", 52000, 0, "1DK", 21.0, None, "即入可", "2026-01-03", "master", "s3"),
        ],
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    row = conn.execute("SELECT building_availability_label FROM building_summaries WHERE building_key='b1'").fetchone()
    conn.close()
    assert row["building_availability_label"] == "入居"


def test_summary_stores_null_move_in_dates_json_when_empty(tmp_path):
    db = tmp_path / "test5.sqlite3"
    conn = connect(db)
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')")
    conn.execute(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            availability_raw, updated_at, source_kind, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("l1", "b1", "Aマンション", "東京都A", "101", 50000, 0, "1K", 20.0, None, "", "2026-01-01", "master", "s1"),
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    row = conn.execute("SELECT move_in_dates_json FROM building_summaries WHERE building_key='b1'").fetchone()
    conn.close()
    assert row["move_in_dates_json"] is None


def test_summary_building_availability_falls_back_to_raw_when_no_date_or_immediate(tmp_path):
    db = tmp_path / "test6.sqlite3"
    conn = connect(db)
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')")
    conn.execute(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            availability_raw, updated_at, source_kind, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("l1", "b1", "Aマンション", "東京都A", "101", 50000, 0, "1K", 20.0, None, "03月下旬", "2026-01-01", "master", "s1"),
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    row = conn.execute("SELECT building_availability_label FROM building_summaries WHERE building_key='b1'").fetchone()
    conn.close()
    assert row["building_availability_label"] == "03月下旬"


def test_summary_building_availability_ulucks_blank_raw_immediate_label(tmp_path):
    db = tmp_path / "test7.sqlite3"
    conn = connect(db)
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')")
    conn.executemany(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            availability_raw, availability_flag_immediate, updated_at, source_kind, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("l1", "b1", "Aマンション", "東京都A", "101", 50000, 0, "1K", 20.0, None, "", 1, "2026-01-01", "master", "s1"),
            ("l2", "b1", "Aマンション", "東京都A", "102", 51000, 0, "1K", 20.5, None, None, 1, "2026-01-02", "master", "s2"),
        ],
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    row = conn.execute(
        "SELECT building_availability_label, move_in_dates_json, vacancy_count FROM building_summaries WHERE building_key='b1'"
    ).fetchone()
    conn.close()

    assert row["vacancy_count"] == 2
    assert row["building_availability_label"] == "入居"
    assert row["move_in_dates_json"] is None


def test_summary_fallbacks_to_buildings_for_zero_vacancy(tmp_path):
    db = tmp_path / "test8.sqlite3"
    conn = connect(db)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, structure, age_years, built_year)
        VALUES ('b-zero','Bマンション','福岡県北九州市小倉北区X', 'SRC', 21, 2004)
        """
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    row = conn.execute(
        """
        SELECT vacancy_count, structure, age_years, building_built_year_month, building_built_age_years, building_structure, building_availability_label
        FROM building_summaries WHERE building_key='b-zero'
        """
    ).fetchone()
    conn.close()

    assert row["vacancy_count"] == 0
    assert row["structure"] == "SRC"
    expected_age = age_years_from_built_year_month("2004-01")
    assert row["age_years"] == expected_age
    assert row["building_built_year_month"] == "2004-01"
    assert row["building_built_age_years"] == expected_age
    assert row["building_structure"] == "SRC"
    assert row["building_availability_label"] is None


def test_summary_uses_current_snapshot_only_and_keeps_zero_vacancy_buildings(tmp_path):
    db = tmp_path / "test9.sqlite3"
    conn = connect(db)
    conn.execute(
        "INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')"
    )
    conn.execute(
        "INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b2','Bマンション','東京都B')"
    )
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (1, 'master', 's1', 'completed')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (2, 'master', 's2', 'completed')")
    conn.execute("INSERT INTO current_ingest_snapshots(source, ingest_run_id) VALUES ('master_import', 2)")
    conn.executemany(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            updated_at, source_kind, source_url, ingest_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("l-old", "b1", "Aマンション", "東京都A", "101", 50000, 0, "1K", 20.0, None, "2026-01-01", "master", "old", 1),
            ("l-new", "b1", "Aマンション", "東京都A", "101", 70000, 0, "1LDK", 30.0, None, "2026-01-02", "master", "new", 2),
        ],
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    a = conn.execute("SELECT vacancy_count, rent_yen_min, rent_yen_max FROM building_summaries WHERE building_key='b1'").fetchone()
    b = conn.execute("SELECT vacancy_count FROM building_summaries WHERE building_key='b2'").fetchone()
    conn.close()

    assert a["vacancy_count"] == 1
    assert a["rent_yen_min"] == 70000
    assert a["rent_yen_max"] == 70000
    assert b["vacancy_count"] == 0


def test_summary_combines_current_snapshots_across_sources(tmp_path):
    db = tmp_path / "test_multi_source.sqlite3"
    conn = connect(db)
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (10, 'master_import', 'm1', 'completed')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (20, 'realpro', 'r1', 'completed')")
    conn.execute("INSERT INTO current_ingest_snapshots(source, ingest_run_id) VALUES ('master_import', 10)")
    conn.execute("INSERT INTO current_ingest_snapshots(source, ingest_run_id) VALUES ('realpro', 20)")
    conn.executemany(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            updated_at, source_kind, source_url, ingest_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("m-1", "b1", "Aマンション", "東京都A", "101", 60000, 0, "1K", 20.0, None, "2026-01-01", "master", "m", 10),
            ("r-1", "b1", "Aマンション", "東京都A", "102", 90000, 0, "2DK", 40.0, None, "2026-01-02", "realpro", "r", 20),
        ],
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    row = conn.execute("SELECT vacancy_count, rent_yen_min, rent_yen_max FROM building_summaries WHERE building_key='b1'").fetchone()
    conn.close()

    assert row["vacancy_count"] == 2
    assert row["rent_yen_min"] == 60000
    assert row["rent_yen_max"] == 90000


def test_non_current_source_run_does_not_replace_other_sources_current_snapshot(tmp_path):
    db = tmp_path / "test_source_isolation.sqlite3"
    conn = connect(db)
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')")
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b2','Bマンション','東京都B')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (10, 'master_import', 'm-current', 'completed')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (11, 'master_import', 'm-old', 'completed')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (20, 'realpro', 'r-current', 'completed')")
    conn.execute("INSERT INTO current_ingest_snapshots(source, ingest_run_id) VALUES ('master_import', 10)")
    conn.execute("INSERT INTO current_ingest_snapshots(source, ingest_run_id) VALUES ('realpro', 20)")
    conn.executemany(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            updated_at, source_kind, source_url, ingest_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("m-current", "b1", "Aマンション", "東京都A", "101", 65000, 0, "1K", 22.0, None, "2026-01-01", "master", "m", 10),
            ("m-not-current", "b1", "Aマンション", "東京都A", "102", 30000, 0, "1R", 15.0, None, "2026-01-05", "master", "m2", 11),
            ("r-current", "b2", "Bマンション", "東京都B", "201", 80000, 0, "2DK", 35.0, None, "2026-01-02", "realpro", "r", 20),
        ],
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    a = conn.execute("SELECT vacancy_count, rent_yen_min, rent_yen_max FROM building_summaries WHERE building_key='b1'").fetchone()
    b = conn.execute("SELECT vacancy_count FROM building_summaries WHERE building_key='b2'").fetchone()
    conn.close()

    assert a["vacancy_count"] == 1
    assert a["rent_yen_min"] == 65000
    assert a["rent_yen_max"] == 65000
    assert b["vacancy_count"] == 1


def test_rental_source_priority_prefers_ulucks_over_mansion_review_chintai(tmp_path):
    db = tmp_path / "test_source_priority.sqlite3"
    conn = connect(db)
    conn.execute("INSERT INTO buildings(building_id, canonical_name, canonical_address) VALUES ('b1','Aマンション','東京都A')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (10, 'ulucks', 'u-current', 'completed')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (20, 'mansion_review_chintai', 'mr-current', 'completed')")
    conn.execute("INSERT INTO current_ingest_snapshots(source, ingest_run_id) VALUES ('ulucks', 10)")
    conn.execute("INSERT INTO current_ingest_snapshots(source, ingest_run_id) VALUES ('mansion_review_chintai', 20)")
    conn.executemany(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            updated_at, source_kind, source_url, ingest_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("u-1", "b1", "Aマンション", "東京都A", "101", 70000, 0, "1K", 22.0, None, "2026-01-03", "ulucks", "u", 10),
            ("mr-1", "b1", "Aマンション", "東京都A", "102", 50000, 0, "1K", 22.0, None, "2026-01-02", "mansion_review_chintai", "mr", 20),
        ],
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    row = conn.execute("SELECT vacancy_count, rent_yen_min, rent_yen_max FROM building_summaries WHERE building_key='b1'").fetchone()
    conn.close()

    assert row["vacancy_count"] == 1
    assert row["rent_yen_min"] == 70000
    assert row["rent_yen_max"] == 70000


def test_sale_summary_generated_from_bunjo_facts_without_sale_listing_count(tmp_path):
    db = tmp_path / "test_sale_summary_without_count.sqlite3"
    conn = connect(db)
    conn.execute(
        """
        INSERT INTO buildings(
            building_id, canonical_name, canonical_address, property_kind,
            sale_price_yen_min, sale_price_yen_max, sale_area_sqm_min, sale_area_sqm_max,
            sale_layout_types_json, sale_listing_count
        ) VALUES ('b-sale','分譲マンション','福岡県北九州市小倉北区X','bunjo',35000000,39000000,65.0,72.0,'["2LDK"]',NULL)
        """
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    summary = conn.execute("SELECT has_sale, sale_listing_count FROM building_summaries WHERE building_key='b-sale'").fetchone()
    sale_summary = conn.execute(
        "SELECT sale_listing_count, price_yen_min, price_yen_max FROM building_sale_summaries WHERE building_key='b-sale'"
    ).fetchone()
    conn.close()

    assert summary["has_sale"] == 1
    assert summary["sale_listing_count"] is None
    assert sale_summary["sale_listing_count"] == 0
    assert sale_summary["price_yen_min"] == 35000000
    assert sale_summary["price_yen_max"] == 39000000


def test_sale_summary_uses_sale_listings_payload(tmp_path):
    db = tmp_path / "test_sale_listings_summary.sqlite3"
    conn = connect(db)
    conn.execute(
        "INSERT INTO buildings(building_id, canonical_name, canonical_address, property_kind, management_style, floor_count_text, total_units) VALUES ('b-sale','分譲マンション','福岡県北九州市小倉北区X','bunjo','巡回','14階建',120)"
    )
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (30, 'mansion_review_mansion', 'sale-current', 'completed')")
    conn.execute("INSERT INTO current_ingest_snapshots(source, ingest_run_id) VALUES ('mansion_review_mansion', 30)")
    conn.executemany(
        """
        INSERT INTO sale_listings(
            sale_listing_key, building_key, source, source_url, evidence_id,
            price_yen, management_fee_yen, repair_fund_yen, tsubo_unit_price_yen, area_sqm, layout, floor_text, direction_text, updated_at, ingest_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("s1", "b-sale", "mansion_review_mansion", "u1", "e1", 36000000, 9000, 7000, 1650000, 66.0, "2LDK", "7階", "南", "2026-01-02", 30),
            ("s2", "b-sale", "mansion_review_mansion", "u2", "e2", 42000000, 12000, 8000, 1820000, 72.0, "3LDK", "10階", "東", "2026-01-03", 30),
        ],
    )
    conn.commit()
    conn.close()

    rebuild(str(db))

    conn = connect(db)
    summary = conn.execute("SELECT sale_price_yen_min, sale_price_yen_max, sale_listing_count, has_sale FROM building_summaries WHERE building_key='b-sale'").fetchone()
    sale_summary = conn.execute(
        "SELECT price_yen_min, price_yen_max, tsubo_unit_price_yen_min, tsubo_unit_price_yen_max, management_fee_yen_min, management_fee_yen_max, repair_fund_yen_min, repair_fund_yen_max, floor_summary, direction_summary, floor_count_text, total_units FROM building_sale_summaries WHERE building_key='b-sale'"
    ).fetchone()
    conn.close()

    assert summary["has_sale"] == 1
    assert summary["sale_listing_count"] == 2
    assert summary["sale_price_yen_min"] == 36000000
    assert summary["sale_price_yen_max"] == 42000000
    assert sale_summary["price_yen_min"] == 36000000
    assert sale_summary["price_yen_max"] == 42000000
    assert sale_summary["tsubo_unit_price_yen_min"] == 1650000
    assert sale_summary["tsubo_unit_price_yen_max"] == 1820000
    assert sale_summary["management_fee_yen_min"] == 9000
    assert sale_summary["management_fee_yen_max"] == 12000
    assert sale_summary["repair_fund_yen_min"] == 7000
    assert sale_summary["repair_fund_yen_max"] == 8000
    assert sale_summary["floor_summary"] == "10階, 7階"
    assert sale_summary["direction_summary"] == "南, 東"
    assert sale_summary["floor_count_text"] == "14階建"
    assert sale_summary["total_units"] == 120
