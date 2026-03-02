from __future__ import annotations

import csv
from pathlib import Path

from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.building_registry.ingest_building_facts import ingest_building_facts_csv


def _write_facts_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "building_name",
                "address",
                "structure",
                "age_years",
                "availability_label",
                "evidence_id",
                "raw_block",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_ingest_building_facts_fill_only_does_not_overwrite_existing_values(tmp_path: Path) -> None:
    db = tmp_path / "facts.sqlite3"
    conn = connect(db)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address, structure, age_years)
        VALUES ('b1','Aマンション','福岡県北九州市小倉北区魚町1-1-1','aまんしょん','北九州市小倉北区魚町1-1-1','SRC',22)
        """
    )
    conn.commit()
    conn.close()

    csv_path = tmp_path / "facts.csv"
    _write_facts_csv(
        csv_path,
        [
            {
                "building_name": "Aマンション",
                "address": "福岡県北九州市小倉北区魚町1-1-1",
                "structure": "RC",
                "age_years": "8",
                "availability_label": "即入居",
                "evidence_id": "mr:1",
                "raw_block": "dummy",
            }
        ],
    )

    report = ingest_building_facts_csv(str(db), str(csv_path), merge="fill_only")
    assert report.matched == 1

    conn = connect(db)
    row = conn.execute("SELECT structure, age_years, availability_label FROM buildings WHERE building_id='b1'").fetchone()
    src = conn.execute("SELECT source, evidence_id, building_id FROM building_sources WHERE evidence_id='mr:1'").fetchone()
    conn.close()

    assert row["structure"] == "SRC"
    assert row["age_years"] == 22
    assert row["availability_label"] == "即入居"
    assert src["building_id"] == "b1"


def test_ingest_building_facts_populates_summaries_for_building_without_listings(tmp_path: Path) -> None:
    db = tmp_path / "facts2.sqlite3"
    conn = connect(db)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address)
        VALUES ('b2','Bマンション','福岡県北九州市門司区栄町1-1-1','bまんしょん','北九州市門司区栄町1-1-1')
        """
    )
    conn.commit()
    conn.close()

    csv_path = tmp_path / "facts2.csv"
    _write_facts_csv(
        csv_path,
        [
            {
                "building_name": "Bマンション",
                "address": "福岡県北九州市門司区栄町1-1-1",
                "structure": "RC",
                "age_years": "5",
                "availability_label": "相談",
                "evidence_id": "mr:2",
                "raw_block": "dummy",
            }
        ],
    )

    ingest_building_facts_csv(str(db), str(csv_path), merge="fill_only")
    rebuild(str(db))

    conn = connect(db)
    row = conn.execute(
        "SELECT vacancy_count, structure, age_years, building_structure, building_built_age_years, building_availability_label FROM building_summaries WHERE building_key='b2'"
    ).fetchone()
    conn.close()

    assert row["vacancy_count"] == 0
    assert row["structure"] == "RC"
    assert row["age_years"] == 5
    assert row["building_structure"] == "RC"
    assert row["building_built_age_years"] == 5
    assert row["building_availability_label"] == "相談"
