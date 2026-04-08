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
                "access_info",
                "floor_count_text",
                "total_units",
                "management_style",
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


def test_ingest_building_facts_repairs_invalid_access_info_for_mansion_review_list_facts(tmp_path: Path) -> None:
    db = tmp_path / "facts5.sqlite3"
    conn = connect(db)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address, access_info)
        VALUES ('b5','Dマンション','福岡県行橋市中央1-1-1','dまんしょん','行橋市中央1-1-1',
        '行橋駅 バス 25 分 築年数 2007年2月 階建て 地上2階建 口コミ数 2 平均賃料 44')
        """
    )
    conn.commit()
    conn.close()

    csv_path = tmp_path / "facts5.csv"
    _write_facts_csv(
        csv_path,
        [
            {
                "building_name": "Dマンション",
                "address": "福岡県行橋市中央1-1-1",
                "access_info": "JR日豊本線(門司港～佐伯) 行橋駅 バス 25 分",
                "evidence_id": "mr:5",
            }
        ],
    )

    ingest_building_facts_csv(str(db), str(csv_path), source="mansion_review_list_facts", merge="fill_only")

    conn = connect(db)
    row = conn.execute("SELECT access_info FROM buildings WHERE building_id='b5'").fetchone()
    conn.close()
    assert row["access_info"] == "JR日豊本線(門司港～佐伯) 行橋駅 バス 25 分"


def test_ingest_building_facts_repairs_invalid_floor_count_text_for_mansion_review_list_facts(tmp_path: Path) -> None:
    db = tmp_path / "facts6.sqlite3"
    conn = connect(db)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address, floor_count_text)
        VALUES ('b6','Eマンション','福岡県北九州市小倉北区浅野1-1-1','eまんしょん','北九州市小倉北区浅野1-1-1','て:地上11階建')
        """
    )
    conn.commit()
    conn.close()

    csv_path = tmp_path / "facts6.csv"
    _write_facts_csv(
        csv_path,
        [
            {
                "building_name": "Eマンション",
                "address": "福岡県北九州市小倉北区浅野1-1-1",
                "floor_count_text": "地上11階建",
                "evidence_id": "mr:6",
            }
        ],
    )

    ingest_building_facts_csv(str(db), str(csv_path), source="mansion_review_list_facts", merge="fill_only")

    conn = connect(db)
    row = conn.execute("SELECT floor_count_text FROM buildings WHERE building_id='b6'").fetchone()
    conn.close()
    assert row["floor_count_text"] == "地上11階建"


def test_ingest_building_facts_keeps_valid_existing_access_info_for_mansion_review_list_facts(tmp_path: Path) -> None:
    db = tmp_path / "facts7.sqlite3"
    conn = connect(db)
    conn.execute(
        """
        INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address, access_info)
        VALUES ('b7','Fマンション','福岡県北九州市小倉北区中島1-1-1','fまんしょん','北九州市小倉北区中島1-1-1',
        'JR日豊本線(門司港～佐伯) 南小倉駅 徒歩 32 分')
        """
    )
    conn.commit()
    conn.close()

    csv_path = tmp_path / "facts7.csv"
    _write_facts_csv(
        csv_path,
        [
            {
                "building_name": "Fマンション",
                "address": "福岡県北九州市小倉北区中島1-1-1",
                "access_info": "南小倉駅 徒歩 32 分",
                "evidence_id": "mr:7",
            }
        ],
    )

    ingest_building_facts_csv(str(db), str(csv_path), source="mansion_review_list_facts", merge="fill_only")

    conn = connect(db)
    row = conn.execute("SELECT access_info FROM buildings WHERE building_id='b7'").fetchone()
    conn.close()
    assert row["access_info"] == "JR日豊本線(門司港～佐伯) 南小倉駅 徒歩 32 分"
