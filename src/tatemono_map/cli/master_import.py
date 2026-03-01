from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

from tatemono_map.db.keys import make_building_key, make_listing_key_for_master
from tatemono_map.normalize.listing_fields import normalize_availability
from tatemono_map.db.repo import connect, replace_building_summary
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.paths import CANONICAL_BUILDINGS_CSV

MASTER_COLUMNS = (
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
    "age_years",
    "structure",
    "raw_block",
)
MASTER_COLUMNS_WITH_EVIDENCE = MASTER_COLUMNS + ("evidence_id",)


MASTER_REQUIRED_COLUMNS = (
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
    "raw_block",
)


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _parse_man_to_yen(value: str | None) -> int | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    return int(float(cleaned.replace(",", "")) * 10000)


def _parse_area(value: str | None) -> float | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    return float(cleaned)


def _parse_int(value: str | None) -> int | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    return int(float(cleaned))


def _fallback_updated_at(value: str | None) -> str:
    cleaned = _clean_text(value)
    if cleaned:
        return cleaned
    return datetime.now().strftime("%Y/%m/%d 00:00")


def _derive_file_from_evidence_id(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    m = re.match(r"^pdf:([^#]+)", cleaned)
    if not m:
        return None
    return m.group(1)


def import_master_csv(db_path: str, csv_path: str) -> tuple[int, int, int]:
    conn = connect(db_path)
    seed_count = 0
    vacancy_count = 0
    seed_summaries: list[dict[str, object]] = []
    touched_buildings: set[str] = set()
    source_url = f"file:{Path(csv_path).name}"

    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM buildings")
        conn.execute("DELETE FROM building_sources")
        conn.execute("DELETE FROM listings")
        conn.execute("DELETE FROM raw_units")
        conn.execute("DELETE FROM raw_sources")

        with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            header = tuple(reader.fieldnames or ())
            missing_required = [column for column in MASTER_REQUIRED_COLUMNS if column not in header]
            if missing_required:
                raise ValueError(
                    f"Unexpected master.csv header. missing_required={missing_required} got={list(header)}"
                )

            for row in reader:
                category = _clean_text(row.get("category"))
                name = _clean_text(row.get("building_name"))
                address = _clean_text(row.get("address"))
                if not name and not address:
                    continue

                building_key = make_building_key(name, address)
                touched_buildings.add(building_key)

                if category in {"seed", "buildings"}:
                    conn.execute(
                        """
                        INSERT INTO buildings(
                            building_id, canonical_name, canonical_address,
                            norm_name, norm_address, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT(building_id) DO UPDATE SET
                            canonical_name=excluded.canonical_name,
                            canonical_address=excluded.canonical_address,
                            norm_name=excluded.norm_name,
                            norm_address=excluded.norm_address,
                            updated_at=CURRENT_TIMESTAMP
                        """,
                        (building_key, name, address, name, address),
                    )
                    summary = {
                        "building_key": building_key,
                        "name": name,
                        "raw_name": name,
                        "address": address,
                        "rent_yen_min": None,
                        "rent_yen_max": None,
                        "area_sqm_min": None,
                        "area_sqm_max": None,
                        "layout_types": [],
                        "move_in_dates": [],
                        "vacancy_count": 0,
                        "last_updated": None,
                    }
                    replace_building_summary(conn, summary)
                    seed_summaries.append(summary)
                    seed_count += 1
                    continue

                raw_block = row.get("raw_block") or ""
                listing_key = make_listing_key_for_master(raw_block)
                updated_at = _fallback_updated_at(row.get("updated_at"))
                rent_yen = _parse_man_to_yen(row.get("rent_man"))
                maint_yen = _parse_man_to_yen(row.get("fee_man"))
                layout = _clean_text(row.get("layout")) or None
                area_sqm = _parse_area(row.get("area_sqm"))
                age_years = _parse_int(row.get("age_years"))
                structure = _clean_text(row.get("structure")) or None
                availability_raw_text = _clean_text(row.get("availability_raw"))
                availability_raw = availability_raw_text or None
                built_raw = _clean_text(row.get("built_raw")) or None
                built_year_month = _clean_text(row.get("built_year_month")) or None
                built_age_years = _parse_int(row.get("built_age_years"))
                explicit_availability_date = _clean_text(row.get("availability_date")) or None
                explicit_immediate_flag = _clean_text(row.get("availability_flag_immediate"))
                immediate_detected, move_in_label, normalized_availability_date = normalize_availability(availability_raw, updated_at, category)
                availability_date = explicit_availability_date or normalized_availability_date
                if explicit_immediate_flag in {"1", "true", "True"}:
                    availability_flag_immediate_value = 1
                elif explicit_immediate_flag in {"0", "false", "False"}:
                    availability_flag_immediate_value = 0
                else:
                    availability_flag_immediate_value = 1 if immediate_detected else 0
                move_in_date = availability_date or (move_in_label or "")
                structure_raw = _clean_text(row.get("structure_raw")) or None
                file_value = _clean_text(row.get("file")) or _derive_file_from_evidence_id(row.get("evidence_id"))

                conn.execute(
                    """
                    INSERT INTO raw_sources(provider, source_kind, source_url, content)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("master_import", "master", source_url, raw_block),
                )
                conn.execute(
                    """
                    INSERT INTO listings(
                        listing_key, building_key, name, address, room_label,
                        rent_yen, maint_yen, layout, area_sqm, move_in_date,
                        age_years, structure, availability_raw, built_raw, structure_raw,
                        built_year_month, built_age_years, availability_date, availability_flag_immediate,
                        updated_at, source_kind, source_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(listing_key) DO UPDATE SET
                        building_key=CASE WHEN excluded.building_key != '' THEN excluded.building_key ELSE listings.building_key END,
                        name=CASE WHEN excluded.name != '' THEN excluded.name ELSE listings.name END,
                        address=CASE WHEN excluded.address != '' THEN excluded.address ELSE listings.address END,
                        room_label=CASE WHEN excluded.room_label != '' THEN excluded.room_label ELSE listings.room_label END,
                        rent_yen=COALESCE(excluded.rent_yen, listings.rent_yen),
                        maint_yen=COALESCE(excluded.maint_yen, listings.maint_yen),
                        layout=CASE WHEN excluded.layout != '' THEN excluded.layout ELSE listings.layout END,
                        area_sqm=COALESCE(excluded.area_sqm, listings.area_sqm),
                        move_in_date=CASE WHEN excluded.move_in_date != '' THEN excluded.move_in_date ELSE listings.move_in_date END,
                        age_years=COALESCE(excluded.age_years, listings.age_years),
                        structure=CASE WHEN excluded.structure != '' THEN excluded.structure ELSE listings.structure END,
                        availability_raw=CASE WHEN excluded.availability_raw != '' THEN excluded.availability_raw ELSE listings.availability_raw END,
                        built_raw=CASE WHEN excluded.built_raw != '' THEN excluded.built_raw ELSE listings.built_raw END,
                        structure_raw=CASE WHEN excluded.structure_raw != '' THEN excluded.structure_raw ELSE listings.structure_raw END,
                        built_year_month=CASE WHEN excluded.built_year_month != '' THEN excluded.built_year_month ELSE listings.built_year_month END,
                        built_age_years=COALESCE(excluded.built_age_years, listings.built_age_years),
                        availability_date=CASE WHEN excluded.availability_date != '' THEN excluded.availability_date ELSE listings.availability_date END,
                        availability_flag_immediate=COALESCE(excluded.availability_flag_immediate, listings.availability_flag_immediate),
                        updated_at=CASE
                            WHEN listings.updated_at IS NULL THEN excluded.updated_at
                            WHEN excluded.updated_at IS NULL THEN listings.updated_at
                            WHEN excluded.updated_at > listings.updated_at THEN excluded.updated_at
                            ELSE listings.updated_at
                        END,
                        source_kind=CASE WHEN excluded.source_kind != '' THEN excluded.source_kind ELSE listings.source_kind END,
                        source_url=CASE WHEN excluded.source_url != '' THEN excluded.source_url ELSE listings.source_url END
                    """,
                    (
                        listing_key,
                        building_key,
                        name,
                        address,
                        "",
                        rent_yen,
                        maint_yen,
                        layout,
                        area_sqm,
                        move_in_date,
                        age_years,
                        structure,
                        availability_raw,
                        built_raw,
                        structure_raw,
                        built_year_month,
                        built_age_years,
                        availability_date,
                        availability_flag_immediate_value,
                        updated_at,
                        "master",
                        file_value or source_url,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO raw_units(
                        listing_key, building_key, name, address, room_label,
                        rent_yen, maint_yen, layout, area_sqm, move_in_date,
                        age_years, structure, availability_raw, built_raw, structure_raw,
                        built_year_month, built_age_years, availability_date, availability_flag_immediate,
                        updated_at, source_kind, source_url, management_company, management_phone
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(listing_key) DO UPDATE SET
                        building_key=CASE WHEN excluded.building_key != '' THEN excluded.building_key ELSE raw_units.building_key END,
                        name=CASE WHEN excluded.name != '' THEN excluded.name ELSE raw_units.name END,
                        address=CASE WHEN excluded.address != '' THEN excluded.address ELSE raw_units.address END,
                        room_label=CASE WHEN excluded.room_label != '' THEN excluded.room_label ELSE raw_units.room_label END,
                        rent_yen=COALESCE(excluded.rent_yen, raw_units.rent_yen),
                        maint_yen=COALESCE(excluded.maint_yen, raw_units.maint_yen),
                        layout=CASE WHEN excluded.layout != '' THEN excluded.layout ELSE raw_units.layout END,
                        area_sqm=COALESCE(excluded.area_sqm, raw_units.area_sqm),
                        move_in_date=CASE WHEN excluded.move_in_date != '' THEN excluded.move_in_date ELSE raw_units.move_in_date END,
                        age_years=COALESCE(excluded.age_years, raw_units.age_years),
                        structure=CASE WHEN excluded.structure != '' THEN excluded.structure ELSE raw_units.structure END,
                        availability_raw=CASE WHEN excluded.availability_raw != '' THEN excluded.availability_raw ELSE raw_units.availability_raw END,
                        built_raw=CASE WHEN excluded.built_raw != '' THEN excluded.built_raw ELSE raw_units.built_raw END,
                        structure_raw=CASE WHEN excluded.structure_raw != '' THEN excluded.structure_raw ELSE raw_units.structure_raw END,
                        built_year_month=CASE WHEN excluded.built_year_month != '' THEN excluded.built_year_month ELSE raw_units.built_year_month END,
                        built_age_years=COALESCE(excluded.built_age_years, raw_units.built_age_years),
                        availability_date=CASE WHEN excluded.availability_date != '' THEN excluded.availability_date ELSE raw_units.availability_date END,
                        availability_flag_immediate=COALESCE(excluded.availability_flag_immediate, raw_units.availability_flag_immediate),
                        updated_at=CASE
                            WHEN raw_units.updated_at IS NULL THEN excluded.updated_at
                            WHEN excluded.updated_at IS NULL THEN raw_units.updated_at
                            WHEN excluded.updated_at > raw_units.updated_at THEN excluded.updated_at
                            ELSE raw_units.updated_at
                        END,
                        source_kind=CASE WHEN excluded.source_kind != '' THEN excluded.source_kind ELSE raw_units.source_kind END,
                        source_url=CASE WHEN excluded.source_url != '' THEN excluded.source_url ELSE raw_units.source_url END,
                        management_company=COALESCE(excluded.management_company, raw_units.management_company),
                        management_phone=COALESCE(excluded.management_phone, raw_units.management_phone)
                    """,
                    (
                        listing_key,
                        building_key,
                        name,
                        address,
                        "",
                        rent_yen,
                        maint_yen,
                        layout,
                        area_sqm,
                        move_in_date,
                        age_years,
                        structure,
                        availability_raw,
                        built_raw,
                        structure_raw,
                        built_year_month,
                        built_age_years,
                        availability_date,
                        availability_flag_immediate_value,
                        updated_at,
                        "master",
                        file_value or source_url,
                        None,
                        None,
                    ),
                )
                vacancy_count += 1

        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()

    rebuild(db_path)
    if vacancy_count == 0 and seed_summaries:
        conn = connect(db_path)
        for summary in seed_summaries:
            replace_building_summary(conn, summary)
        conn.commit()
        conn.close()
    return seed_count, vacancy_count, len(touched_buildings)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/tatemono_map.sqlite3")
    parser.add_argument("--csv", default=str(CANONICAL_BUILDINGS_CSV))
    args = parser.parse_args()

    seed_count, vacancy_count, unique_buildings = import_master_csv(args.db, args.csv)
    print(f"seed={seed_count} vacancy={vacancy_count} unique_buildings={unique_buildings}")


if __name__ == "__main__":
    main()
