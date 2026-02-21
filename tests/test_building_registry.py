from pathlib import Path

from tatemono_map.building_registry.ingest_master_import import ingest_master_import_csv
from tatemono_map.building_registry.seed_from_ui import seed_from_ui_csv
from tatemono_map.db.repo import connect


def test_seed_and_weekly_ingest_use_canonical_buildings(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    seed_csv = tmp_path / "buildings_seed_ui.csv"
    master_csv = tmp_path / "master_import.csv"

    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n"
        "Aマンション,福岡県北九州市小倉北区魚町1-1-1,ui:a,\n"
        "Aマンション別表記,福岡県北九州市小倉北区魚町1-1-1,ui:a_alias,ui:a\n",
        encoding="utf-8",
    )

    inserted, attached = seed_from_ui_csv(str(db_path), str(seed_csv))
    assert inserted == 1
    assert attached == 2

    master_csv.write_text(
        "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id\n"
        "1,vacancy,2026/01/01 10:00,Aマンション,101,福岡県北九州市小倉北区魚町1-1-1,10.1,0.5,1,1K,20.1,10,RC,raw-a,pdf:a\n"
        "1,vacancy,2026/01/02 11:00,新規マンション,201,福岡県北九州市小倉南区城野2-2-2,12.2,0.3,2,1LDK,30.1,8,RC,raw-b,pdf:b\n",
        encoding="utf-8",
    )

    report = ingest_master_import_csv(str(db_path), str(master_csv))
    assert report.newly_added == 1
    assert report.attached_listings == 2

    conn = connect(db_path)
    buildings_count = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    assert buildings_count == 2

    canonical_name = conn.execute("SELECT canonical_name FROM buildings WHERE canonical_name='Aマンション'").fetchone()
    assert canonical_name is not None

    listing_rows = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    assert listing_rows == 2
    conn.close()
