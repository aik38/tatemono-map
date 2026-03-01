from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from tatemono_map.db.keys import make_building_key, make_listing_key_for_smartlink
from tatemono_map.db.schema import ensure_schema, normalize_db_path


@dataclass
class ListingRecord:
    name: str
    address: str
    rent_yen: int | None
    area_sqm: float | None
    layout: str | None
    updated_at: str | None
    source_kind: str
    source_url: str
    room_label: str | None = None
    maint_yen: int | None = None
    move_in_date: str | None = None
    management_company: str | None = None
    management_phone: str | None = None


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = ensure_schema(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_db_path(db_path: str | Path) -> Path:
    return normalize_db_path(db_path)


def insert_raw_source(conn: sqlite3.Connection, provider: str, source_kind: str, source_url: str, content: str) -> None:
    conn.execute(
        "INSERT INTO raw_sources(provider, source_kind, source_url, content) VALUES(?, ?, ?, ?)",
        (provider, source_kind, source_url, content),
    )
    conn.commit()


def iter_raw_sources(conn: sqlite3.Connection, source_kind: str) -> Iterator[sqlite3.Row]:
    rows = conn.execute(
        "SELECT source_url, content, fetched_at FROM raw_sources WHERE source_kind=? ORDER BY id ASC",
        (source_kind,),
    ).fetchall()
    for row in rows:
        yield row


def upsert_listing(conn: sqlite3.Connection, record: ListingRecord) -> None:
    building_key = make_building_key(record.name, record.address)
    listing_key = make_listing_key_for_smartlink(record.source_url, record.room_label)
    conn.execute(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            updated_at, source_kind, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_key) DO UPDATE SET
            building_key=excluded.building_key,
            name=excluded.name,
            address=excluded.address,
            room_label=excluded.room_label,
            rent_yen=excluded.rent_yen,
            maint_yen=excluded.maint_yen,
            layout=excluded.layout,
            area_sqm=excluded.area_sqm,
            move_in_date=excluded.move_in_date,
            updated_at=excluded.updated_at,
            source_kind=excluded.source_kind,
            source_url=excluded.source_url
        """,
        (
            listing_key,
            building_key,
            record.name,
            record.address,
            record.room_label,
            record.rent_yen,
            record.maint_yen,
            record.layout,
            record.area_sqm,
            record.move_in_date,
            record.updated_at,
            record.source_kind,
            record.source_url,
        ),
    )

    conn.execute(
        """
        INSERT INTO raw_units(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            updated_at, source_kind, source_url, management_company, management_phone
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_key) DO UPDATE SET
            building_key=excluded.building_key,
            name=excluded.name,
            address=excluded.address,
            room_label=excluded.room_label,
            rent_yen=excluded.rent_yen,
            maint_yen=excluded.maint_yen,
            layout=excluded.layout,
            area_sqm=excluded.area_sqm,
            move_in_date=excluded.move_in_date,
            updated_at=excluded.updated_at,
            source_kind=excluded.source_kind,
            source_url=excluded.source_url,
            management_company=excluded.management_company,
            management_phone=excluded.management_phone
        """,
        (
            listing_key,
            building_key,
            record.name,
            record.address,
            record.room_label,
            record.rent_yen,
            record.maint_yen,
            record.layout,
            record.area_sqm,
            record.move_in_date,
            record.updated_at,
            record.source_kind,
            record.source_url,
            record.management_company,
            record.management_phone,
        ),
    )
    conn.commit()


def replace_building_summary(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO building_summaries(
            building_key, name, raw_name, address,
            rent_yen_min, rent_yen_max, area_sqm_min, area_sqm_max,
            layout_types_json, move_in_dates_json, age_years, structure,
            building_built_year_month, building_built_age_years, building_structure, building_availability_label,
            vacancy_count, last_updated, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(building_key) DO UPDATE SET
            name=excluded.name,
            raw_name=excluded.raw_name,
            address=excluded.address,
            rent_yen_min=excluded.rent_yen_min,
            rent_yen_max=excluded.rent_yen_max,
            area_sqm_min=excluded.area_sqm_min,
            area_sqm_max=excluded.area_sqm_max,
            layout_types_json=excluded.layout_types_json,
            move_in_dates_json=excluded.move_in_dates_json,
            age_years=excluded.age_years,
            structure=excluded.structure,
            building_built_year_month=excluded.building_built_year_month,
            building_built_age_years=excluded.building_built_age_years,
            building_structure=excluded.building_structure,
            building_availability_label=excluded.building_availability_label,
            vacancy_count=excluded.vacancy_count,
            last_updated=excluded.last_updated,
            updated_at=excluded.updated_at
        """,
        (
            row["building_key"],
            row.get("name"),
            row.get("raw_name"),
            row.get("address"),
            row.get("rent_yen_min"),
            row.get("rent_yen_max"),
            row.get("area_sqm_min"),
            row.get("area_sqm_max"),
            json.dumps(row.get("layout_types") or [], ensure_ascii=False),
            (json.dumps(row.get("move_in_dates"), ensure_ascii=False) if row.get("move_in_dates") else None),
            row.get("age_years"),
            row.get("structure"),
            row.get("building_built_year_month"),
            row.get("building_built_age_years"),
            row.get("building_structure"),
            row.get("building_availability_label"),
            row.get("vacancy_count"),
            row.get("last_updated"),
            row.get("last_updated"),
        ),
    )
    conn.commit()
