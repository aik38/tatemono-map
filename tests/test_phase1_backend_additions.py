from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from tatemono_map.building_registry.common import normalize_source_name
from tatemono_map.building_registry.ingest_master_import import ingest_master_import_csv
from tatemono_map.db.repo import connect
from tatemono_map.db.schema import ensure_schema


def test_normalize_source_name_maps_priority_sources() -> None:
    assert normalize_source_name("master_import", category="ulucks") == "ulucks"
    assert normalize_source_name("master_import", category="realpro") == "realpro"
    assert normalize_source_name("mansion_review_list_facts", category="chintai") == "mansion_review_chintai"
    assert normalize_source_name("mansion_review_list_facts", category="mansion") == "mansion_review_mansion"


def test_ensure_schema_adds_phase1_tables_and_seeds_source_priority(tmp_path: Path) -> None:
    db_path = tmp_path / "phase1.sqlite3"
    ensure_schema(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for required in ("area_master", "source_priority", "sale_listings", "unmatched_queue", "qc_run_reports"):
            assert required in tables

        rows = conn.execute(
            "SELECT domain, source, priority_rank FROM source_priority WHERE enabled=1 ORDER BY domain, priority_rank"
        ).fetchall()

    assert ("rental", "ulucks", 1) in rows
    assert ("rental", "realpro", 2) in rows
    assert ("rental", "mansion_review_chintai", 3) in rows
    assert ("sale", "mansion_review_mansion", 1) in rows


def test_ingest_master_import_dual_writes_unmatched_queue(tmp_path: Path) -> None:
    db_path = tmp_path / "master.sqlite3"
    ensure_schema(db_path)

    csv_path = tmp_path / "master_import.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "page",
                "category",
                "updated_at",
                "building_name",
                "room",
                "address",
                "rent_man",
                "fee_man",
                "floor",
                "layout",
                "area_sqm",
                "availability_raw",
                "built_raw",
                "age_years",
                "structure",
                "built_year_month",
                "built_age_years",
                "availability_date",
                "availability_flag_immediate",
                "structure_raw",
                "raw_block",
                "evidence_id",
            ]
        )
        writer.writerow(["1", "ulucks", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "dummy", "ev:1"])

    report = ingest_master_import_csv(str(db_path), str(csv_path), source="master_import")
    assert report.unresolved == 1

    conn = connect(db_path)
    row = conn.execute(
        "SELECT domain, source, reason, evidence_id FROM unmatched_queue ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["domain"] == "rental"
    assert row["source"] == "ulucks"
    assert row["reason"] == "missing_name_and_address"
    assert row["evidence_id"] == "ev:1"
