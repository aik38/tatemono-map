from pathlib import Path

from tatemono_map.building_registry.ingest_master_import import ingest_master_import_csv
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
    assert first == (1, 2)
    assert second == (0, 2)

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

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0] == 3
    canonical = conn.execute(
        "SELECT canonical_name, canonical_address FROM buildings WHERE canonical_name='Aマンション'"
    ).fetchone()
    assert tuple(canonical) == ("Aマンション", "福岡県北九州市小倉北区魚町1-1-1")
    conn.close()

    review_dir = Path("tmp/review")
    assert list(review_dir.glob("new_buildings_*.csv"))
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
