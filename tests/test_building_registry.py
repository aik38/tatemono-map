from pathlib import Path

from tatemono_map.building_registry.ingest_master_import import ingest_master_import_csv
from tatemono_map.building_registry.ingest_master_import import set_current_snapshot
from tatemono_map.building_registry.ingest_master_import import set_current_snapshot_to_latest_completed
from tatemono_map.building_registry.keys import make_alias_key
from tatemono_map.building_registry.seed_from_ui import seed_from_ui_csv
from tatemono_map.db.repo import connect


def test_seed_idempotency_preserves_canonical(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "Aマンション,福岡県北九州市小倉北区魚町1-1-1,ui:a,\n"
        "Aマンション別表記,福岡県北九州市小倉北区魚町1-1-1,ui:a_alias,ui:a\n",
        encoding="utf-8",
    )

    first = seed_from_ui_csv(str(db_path), str(seed_csv))
    second = seed_from_ui_csv(str(db_path), str(seed_csv))
    assert first == (1, 2, 1)
    assert second == (0, 2, 1)

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0] == 1
    canonical = conn.execute("SELECT canonical_name, canonical_address FROM buildings").fetchone()
    assert tuple(canonical) == ("Aマンション", "福岡県北九州市小倉北区魚町1-1-1")
    conn.close()


def test_weekly_update_idempotency_and_review_csv(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    master_csv = tmp_path / "master_import.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "Aマンション,福岡県北九州市小倉北区魚町1-1-1,ui:a,\n"
        "Aマンション2,福岡県北九州市小倉北区魚町1-1-1,ui:a2,\n",
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))
    conn = connect(db_path)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address)
        VALUES ('manual-b', '別建物', '福岡県北九州市小倉北区魚町1-1-1', '別建物', '福岡県北九州市小倉北区魚町1-1-1')
        """
    )
    conn.commit()
    conn.close()

    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/01 10:00,Aマンション,101,福岡県北九州市小倉北区魚町1-1-1,10.1,0.5,1,1K,20.1,10,RC,raw-a,pdf:a\n"
        "1,vacancy,2026/01/02 11:00,新規マンション,201,福岡県北九州市小倉南区城野2-2-2,12.2,0.3,2,1LDK,30.1,8,RC,raw-b,pdf:b\n"
        "1,vacancy,2026/01/03 12:00,曖昧マンション,301,福岡県北九州市小倉北区魚町1-1-1,11.0,0.2,3,1LDK,28.0,7,RC,raw-c,pdf:c\n",
        encoding="utf-8",
    )

    r1 = ingest_master_import_csv(str(db_path), str(master_csv))
    r2 = ingest_master_import_csv(str(db_path), str(master_csv))
    assert r1.newly_added == 1
    assert r2.newly_added == 0
    assert r1.auto_seeded_count == 1
    assert r1.auto_seed_blocked_count >= 0
    assert r1.suspect_count >= 1
    assert r1.unmatched_count >= 1

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0] == 3
    canonical = conn.execute(
        "SELECT canonical_name, canonical_address FROM buildings WHERE canonical_name='Aマンション'"
    ).fetchone()
    assert tuple(canonical) == ("Aマンション", "福岡県北九州市小倉北区魚町1-1-1")
    conn.close()

    review_dir = Path("tmp/review")
    assert list(review_dir.glob("suspects_*.csv"))
    assert list(review_dir.glob("unmatched_listings_*.csv"))


def test_match_priority_alias_then_address_then_similarity(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "Aマンション,福岡県北九州市小倉北区魚町1-1-1,ui:a,\n"
        "Bマンション,福岡県北九州市小倉南区城野2-2-2,ui:b,\n"
        "A別名,福岡県北九州市小倉南区城野2-2-2,ui:a_alias,ui:a\n",
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))

    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/01 10:00,A別名,101,福岡県北九州市小倉南区城野2-2-2,10.1,0.5,1,1K,20.1,10,RC,raw-a,pdf:a\n"
        "1,vacancy,2026/01/02 11:00,Bマンション,102,福岡県北九州市小倉南区城野2-2-2,10.1,0.5,1,1K,20.1,10,RC,raw-b,pdf:b\n",
        encoding="utf-8",
    )

    ingest_master_import_csv(str(db_path), str(master_csv))

    conn = connect(db_path)
    rows = conn.execute(
        "SELECT source, evidence_id, building_id FROM building_sources WHERE source='master_import' ORDER BY evidence_id"
    ).fetchall()
    mapping = {row[1]: row[2] for row in rows}

    aid = conn.execute("SELECT building_id FROM buildings WHERE canonical_name='Aマンション'").fetchone()[0]
    bid = conn.execute("SELECT building_id FROM buildings WHERE canonical_name='Bマンション'").fetchone()[0]

    assert mapping["pdf:a"] == aid  # alias hit should beat address hit to B
    assert mapping["pdf:b"] == bid  # direct address exact match
    conn.close()


def test_ingest_accepts_pdf_final_16_column_header(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "Aマンション,福岡県北九州市小倉北区魚町1-1-1,ui:a,\n",
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))

    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "category,updated_at,building_name,room,address,rent_man,fee_man,layout,floor,area_sqm,age_years,structure,file,page,raw_block,evidence_id\n"
        "vacancy,2026/01/01 10:00,Aマンション,101,福岡県北九州市小倉北区魚町1-1-1,10.1,0.5,1K,1,20.1,10,RC,a.pdf,1,raw-a,pdf:a\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv))
    assert report.attached_listings == 1

    conn = connect(db_path)
    row = conn.execute("SELECT COUNT(*) AS c, MAX(age_years) AS age_years, MAX(structure) AS structure FROM listings").fetchone()
    conn.close()
    assert row["c"] == 1
    assert row["age_years"] == 10
    assert row["structure"] == "RC"


def test_normalize_building_input_strips_prefecture_prefix() -> None:
    from tatemono_map.building_registry.normalization import normalize_building_input

    normalized = normalize_building_input("x", "福岡県北九州市小倉北区上富野3-4-5")
    assert normalized.normalized_address == "北九州市小倉北区上富野3-4-5"


def test_match_building_ignores_prefecture_on_both_sides(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "県なしマンション,北九州市小倉北区魚町1-1-1,ui:a,\n"
        "県ありマンション,福岡県北九州市小倉南区城野2-2-2,ui:b,\n",
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))

    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/01 10:00,県なしマンション,101,福岡県北九州市小倉北区魚町1-1-1,10.1,0.5,1,1K,20.1,10,RC,raw-a,pdf:a\n"
        "1,vacancy,2026/01/02 11:00,県ありマンション,102,北九州市小倉南区城野2-2-2,10.1,0.5,1,1K,20.1,10,RC,raw-b,pdf:b\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv))
    assert report.attached_listings == 2

    conn = connect(db_path)
    rows = conn.execute(
        "SELECT evidence_id, building_id FROM building_sources WHERE source='master_import' ORDER BY evidence_id"
    ).fetchall()
    mapping = {row[0]: row[1] for row in rows}

    no_pref_id = conn.execute(
        "SELECT building_id FROM buildings WHERE canonical_name='県なしマンション'"
    ).fetchone()[0]
    with_pref_id = conn.execute(
        "SELECT building_id FROM buildings WHERE canonical_name='県ありマンション'"
    ).fetchone()[0]

    assert mapping["pdf:a"] == no_pref_id
    assert mapping["pdf:b"] == with_pref_id
    conn.close()


def test_ingest_master_import_routes_mansion_to_sale_listings(tmp_path: Path) -> None:
    db_path = tmp_path / "registry_sale.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "分譲テストマンション,福岡県北九州市小倉北区魚町1-1-1,ui:sale,\n",
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))

    master_csv = tmp_path / "master_import_sale.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,availability_raw,built_raw,age_years,structure,built_year_month,built_age_years,availability_date,availability_flag_immediate,structure_raw,raw_block,evidence_id\n"
        "1,mansion,2026/01/01 10:00,分譲テストマンション,701,福岡県北九州市小倉北区魚町1-1-1,3980,,7階,3LDK,72.5,,,,,2010-01,,,,,\"管理費:12000円 | 修繕積立金:8000円 | 坪単価:182万円/坪 | 向き:南\",e1\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv), source="mansion_review_list_facts")
    assert report.attached_listings == 1

    conn = connect(db_path)
    rental_count = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
    sale = conn.execute(
        "SELECT source, price_yen, management_fee_yen, repair_fund_yen, tsubo_unit_price_yen, floor_text, direction_text FROM sale_listings"
    ).fetchone()
    conn.close()

    assert rental_count == 0
    assert sale["source"] == "mansion_review_mansion"
    assert sale["price_yen"] == 39800000
    assert sale["management_fee_yen"] == 12000
    assert sale["repair_fund_yen"] == 8000
    assert sale["tsubo_unit_price_yen"] == 1820000
    assert sale["floor_text"] == "7階"
    assert sale["direction_text"] == "南"


def test_ingest_master_import_keeps_access_and_floor_count_labels_from_raw_block(tmp_path: Path) -> None:
    db_path = tmp_path / "registry_access.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "アクセステストマンション,福岡県北九州市門司区柳町1-1-1,ui:access,\n",
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))

    master_csv = tmp_path / "master_import_access.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,availability_raw,built_raw,age_years,structure,built_year_month,built_age_years,availability_date,availability_flag_immediate,structure_raw,raw_block,evidence_id\n"
        "1,chintai,2026/04/01 10:00,アクセステストマンション,101,福岡県北九州市門司区柳町1-1-1,4.6,0.3,1階,1K,27.9,,,,,,,,,,\"交通:JR山陽本線(岩国～門司) 門司駅 徒歩4分 | 階建て:地上14階建\",e1\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv), source="mansion_review_list")
    assert report.attached_listings == 1

    conn = connect(db_path)
    building = conn.execute(
        "SELECT access_info, floor_count_text FROM buildings WHERE canonical_name='アクセステストマンション'"
    ).fetchone()
    conn.close()

    assert building["access_info"] == "JR山陽本線(岩国～門司) 門司駅 徒歩4分"
    assert building["floor_count_text"] == "地上14階建"


def test_ingest_auto_renormalizes_buildings_norm_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    conn = connect(db_path)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address)
        VALUES ('b1', 'Aマンション', '福岡県北九州市小倉北区魚町1丁目1番1号', 'Aマンション', '福岡県北九州市小倉北区魚町1丁目1番1号')
        """
    )
    conn.commit()
    conn.close()

    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/01 10:00,Aマンション,101,福岡県北九州市小倉北区魚町1-1-1,10.1,0.5,1,1K,20.1,10,RC,raw-a,pdf:a\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv))
    assert report.attached_listings == 1
    assert report.unresolved == 0

    conn = connect(db_path)
    norm_address = conn.execute("SELECT norm_address FROM buildings WHERE building_id='b1'").fetchone()[0]
    conn.close()
    assert "丁目" not in norm_address
    assert "番" not in norm_address
    assert "号" not in norm_address


def test_alias_key_is_shared_between_seed_and_ingest(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "Aマンション,福岡県北九州市小倉北区魚町1-1-1,ui:a,\n"
        "A別名,福岡県北九州市小倉北区魚町1-1-1,ui:a_alias,ui:a\n",
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))

    conn = connect(db_path)
    conn.execute("DELETE FROM building_sources WHERE source='ui_seed' AND evidence_id='ui:a_alias'")
    conn.commit()
    alias_key = conn.execute("SELECT alias_key FROM building_key_aliases").fetchone()[0]
    conn.close()

    expected_key = make_alias_key("A別名", "北九州市小倉北区魚町1-1-1")
    assert alias_key == expected_key

    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/01 10:00,A別名,101,福岡県北九州市小倉北区魚町1-1-1,10.1,0.5,1,1K,20.1,10,RC,raw-a,pdf:a\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv))
    assert report.unresolved == 0

    conn = connect(db_path)
    matched = conn.execute(
        "SELECT building_id FROM building_sources WHERE source='master_import' AND evidence_id='pdf:a'"
    ).fetchone()[0]
    winner_id = conn.execute(
        "SELECT building_id FROM building_sources WHERE source='ui_seed' AND evidence_id='ui:a'"
    ).fetchone()[0]
    conn.close()
    assert matched == winner_id


def test_ingest_accepts_header_without_age_structure_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "Aマンション,福岡県北九州市小倉北区魚町1-1-1,ui:a,\n",
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))

    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,raw_block,evidence_id\n"
        "1,vacancy,2026/01/01 10:00,Aマンション,101,福岡県北九州市小倉北区魚町1-1-1,10.1,0.5,1,1K,20.1,raw-a,pdf:a\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv))
    assert report.attached_listings == 1

    conn = connect(db_path)
    row = conn.execute("SELECT age_years, structure FROM listings").fetchone()
    conn.close()
    assert row["age_years"] is None
    assert row["structure"] is None


def test_failed_run_cannot_become_current_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    conn = connect(db_path)
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (10, 'master_import', 'ok', 'completed')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (11, 'master_import', 'ng', 'failed')")
    set_current_snapshot(conn, "master_import", 10)
    conn.commit()

    import pytest

    with pytest.raises(RuntimeError):
        set_current_snapshot(conn, "master_import", 11)

    current = conn.execute("SELECT ingest_run_id FROM current_ingest_snapshots WHERE source='master_import'").fetchone()[0]
    conn.close()
    assert current == 10


def test_set_current_snapshot_to_latest_completed_selects_latest_id_for_same_source(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    conn = connect(db_path)
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (1, 'master_import', 'r1', 'completed')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (2, 'master_import', 'r2', 'failed')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (3, 'master_import', 'r3', 'completed')")
    conn.execute("INSERT INTO ingest_runs(id, source, snapshot_key, status) VALUES (4, 'realpro', 'x1', 'completed')")

    latest = set_current_snapshot_to_latest_completed(conn, "master_import")
    conn.commit()

    current = conn.execute("SELECT ingest_run_id FROM current_ingest_snapshots WHERE source='master_import'").fetchone()[0]
    conn.close()

    assert latest == 3
    assert current == 3


def test_ingest_auto_seeds_high_confidence_unmatched_and_preserves_traceability(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/02 11:00,新規マンション,201,福岡県北九州市小倉南区城野2-2-2,12.2,0.3,2,1LDK,30.1,8,RC,raw-b,pdf:b\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv))

    assert report.newly_added == 1
    assert report.auto_seeded_count == 1
    assert report.unresolved == 0

    conn = connect(db_path)
    row = conn.execute(
        "SELECT building_id, canonical_name, canonical_address FROM buildings WHERE canonical_name='新規マンション'"
    ).fetchone()
    src = conn.execute(
        "SELECT building_id FROM building_sources WHERE source='master_import' AND evidence_id='pdf:b'"
    ).fetchone()
    alias = conn.execute(
        "SELECT canonical_key FROM building_key_aliases WHERE alias_key=?",
        (row[0],),
    ).fetchone()
    listing = conn.execute("SELECT building_key FROM listings").fetchone()
    conn.close()

    assert row is not None
    assert src[0] == row[0]
    assert alias[0] == row[0]
    assert listing[0] == row[0]


def test_ingest_low_confidence_unmatched_stays_review_only(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "既存マンション,福岡県北九州市小倉北区魚町1-1-1,ui:a,\n",
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))

    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/03 12:00,既存マンション別棟,301,福岡県北九州市小倉北区魚町1丁目,11.0,0.2,3,1LDK,28.0,7,RC,raw-c,pdf:c\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv))

    assert report.newly_added == 0
    assert report.auto_seed_blocked_count == 1
    assert report.unresolved == 1

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
    conn.close()


def test_ingest_disable_auto_seed_keeps_unmatched_review_only(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/02 11:00,無効化テストマンション,201,福岡県北九州市小倉南区城野2-2-2,12.2,0.3,2,1LDK,30.1,8,RC,raw-b,pdf:disable\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv), auto_seed_high_confidence=False)

    assert report.auto_seed_enabled is False
    assert report.newly_added == 0
    assert report.unresolved == 1

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0] == 0
    conn.close()


def test_future_ingest_matches_auto_seeded_building_stably(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    master_csv = tmp_path / "master_import.csv"
    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/02 11:00,継続マッチマンション,201,福岡県北九州市小倉南区城野2-2-2,12.2,0.3,2,1LDK,30.1,8,RC,raw-1,pdf:one\n",
        encoding="utf-8",
    )
    first = ingest_master_import_csv(str(db_path), str(master_csv))

    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/09 11:00,継続マッチマンション,301,福岡県北九州市小倉南区城野2-2-2,12.8,0.3,3,1LDK,31.0,8,RC,raw-2,pdf:two\n",
        encoding="utf-8",
    )
    second = ingest_master_import_csv(str(db_path), str(master_csv))

    assert first.auto_seeded_count == 1
    assert second.auto_seeded_count == 0

    conn = connect(db_path)
    ids = conn.execute(
        "SELECT evidence_id, building_id FROM building_sources WHERE source='master_import' ORDER BY evidence_id"
    ).fetchall()
    conn.close()

    assert len(ids) == 2
    assert ids[0][1] == ids[1][1]
