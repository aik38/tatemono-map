from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from tatemono_map.db.keys import make_building_key, make_listing_key_for_master
from tatemono_map.db.repo import connect, replace_building_summary
from tatemono_map.normalize.building_summaries import rebuild

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


def _fallback_updated_at(value: str | None) -> str:
    cleaned = _clean_text(value)
    if cleaned:
        return cleaned
    return datetime.now().strftime("%Y/%m/%d 00:00")


def import_master_csv(db_path: str, csv_path: str) -> tuple[int, int, int]:
    conn = connect(db_path)
    conn.execute("DELETE FROM listings")
    conn.execute("DELETE FROM raw_units")
    conn.execute("DELETE FROM raw_sources")

    seed_count = 0
    vacancy_count = 0
    seed_summaries: list[dict[str, object]] = []
    touched_buildings: set[str] = set()
    source_url = f"file:{Path(csv_path).name}"

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = tuple(reader.fieldnames or ())
        if header not in (MASTER_COLUMNS, MASTER_COLUMNS_WITH_EVIDENCE):
            raise ValueError(f"Unexpected master.csv header: {reader.fieldnames}")

        for row in reader:
            category = _clean_text(row.get("category"))
            name = _clean_text(row.get("building_name"))
            address = _clean_text(row.get("address"))
            if not name and not address:
                continue

            building_key = make_building_key(name, address)
            touched_buildings.add(building_key)

            if category == "seed":
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
                    updated_at, source_kind, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    None,
                    updated_at,
                    "master",
                    source_url,
                ),
            )
            conn.execute(
                """
                INSERT INTO raw_units(
                    listing_key, building_key, name, address, room_label,
                    rent_yen, maint_yen, layout, area_sqm, move_in_date,
                    updated_at, source_kind, source_url, management_company, management_phone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    None,
                    updated_at,
                    "master",
                    source_url,
                    None,
                    None,
                ),
            )
            vacancy_count += 1

    conn.commit()
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
    parser.add_argument("--csv", required=True)
    args = parser.parse_args()

    seed_count, vacancy_count, unique_buildings = import_master_csv(args.db, args.csv)
    print(f"seed={seed_count} vacancy={vacancy_count} unique_buildings={unique_buildings}")


if __name__ == "__main__":
    main()
