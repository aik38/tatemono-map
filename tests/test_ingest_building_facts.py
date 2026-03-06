from __future__ import annotations

import csv
from pathlib import Path

from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.building_registry.ingest_building_facts import ingest_building_facts_csv
from tatemono_map.util.building_age import age_years_from_built_year_month


def _write_facts_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "building_name",
                "address",
                "structure",
                "age_years",
                "built_year_month",
                "property_kind",
                "sale_price_yen_min",
                "sale_price_yen_max",
                "sale_price_yen_avg",
                "sale_area_sqm_min",
                "sale_area_sqm_max",
                "sale_layout_types_json",
                "sale_listing_count",
                "avg_rent_yen",
                "rental_listing_count",
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

    report = ingest_building_facts_csv(str(db), str(csv_path), source="manual_facts", merge="fill_only")
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
    assert row["building_availability_label"] is None


def test_ingest_building_facts_updates_bunjo_fields(tmp_path: Path) -> None:
    db = tmp_path / "facts3.sqlite3"
    conn = connect(db)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address)
        VALUES ('b3','Cマンション','北九州市小倉北区浅野2-1-1','cまんしょん','北九州市小倉北区浅野2-1-1')
        """
    )
    conn.commit()
    conn.close()

    csv_path = tmp_path / "facts3.csv"
    _write_facts_csv(
        csv_path,
        [
            {
                "building_name": "Cマンション",
                "address": "北九州市小倉北区浅野2-1-1",
                "structure": "RC",
                "age_years": "",
                "built_year_month": "2011-02",
                "property_kind": "bunjo",
                "sale_price_yen_min": "39800000",
                "sale_price_yen_max": "42000000",
                "sale_price_yen_avg": "40410000",
                "sale_area_sqm_min": "65",
                "sale_area_sqm_max": "70.1",
                "sale_layout_types_json": "[\"2LDK\",\"3LDK\"]",
                "sale_listing_count": "2",
                "avg_rent_yen": "",
                "rental_listing_count": "",
                "availability_label": "",
                "evidence_id": "mr:3",
                "raw_block": "dummy",
            }
        ],
    )

    ingest_building_facts_csv(str(db), str(csv_path), merge="fill_only")
    rebuild(str(db))

    conn = connect(db)
    row = conn.execute(
        "SELECT property_kind, sale_price_yen_avg, sale_listing_count, building_built_year_month, building_availability_label FROM building_summaries WHERE building_key='b3'"
    ).fetchone()
    conn.close()

    assert row["property_kind"] == "bunjo"
    assert row["sale_price_yen_avg"] == 40410000
    assert row["sale_listing_count"] == 2
    assert row["building_built_year_month"] == "2011-02"
    assert row["building_availability_label"] is None


def test_ingest_building_facts_recalculates_age_from_built_year_month_for_existing_record(tmp_path: Path) -> None:
    db = tmp_path / "facts4.sqlite3"
    conn = connect(db)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address, age_years)
        VALUES ('b4','サンパーク門司港','北九州市門司区港町1-1','さんぱーくもじこう','北九州市門司区港町1-1',1)
        """
    )
    conn.commit()
    conn.close()

    csv_path = tmp_path / "facts4.csv"
    _write_facts_csv(
        csv_path,
        [
            {
                "building_name": "サンパーク門司港",
                "address": "北九州市門司区港町1-1",
                "built_year_month": "2001-05",
                "property_kind": "bunjo",
                "evidence_id": "mr:4",
            }
        ],
    )

    ingest_building_facts_csv(str(db), str(csv_path), source="mansion_review_list_facts", merge="fill_only")
    rebuild(str(db))

    conn = connect(db)
    building_row = conn.execute("SELECT age_years, built_year_month FROM buildings WHERE building_id='b4'").fetchone()
    summary_row = conn.execute(
        "SELECT age_years, building_built_age_years FROM building_summaries WHERE building_key='b4'"
    ).fetchone()
    conn.close()

    expected_age = age_years_from_built_year_month("2001-05")
    assert expected_age is not None
    assert building_row["built_year_month"] == "2001-05"
    assert building_row["age_years"] == expected_age
    assert summary_row["age_years"] == expected_age
    assert summary_row["building_built_age_years"] == expected_age
