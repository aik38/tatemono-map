from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tatemono_map.util.text import normalize_text


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


def _hash_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _building_key(name: str, address: str) -> str:
    return _hash_key(f"{normalize_text(name)}|{normalize_text(address)}")


def _listing_key(source_url: str, room_label: str | None) -> str:
    return _hash_key(f"{source_url}|{normalize_text(room_label or '')}")


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_url TEXT NOT NULL,
            raw_html TEXT NOT NULL,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_key TEXT UNIQUE,
            building_key TEXT,
            name TEXT,
            address TEXT,
            room_label TEXT,
            rent_yen INTEGER,
            maint_yen INTEGER,
            layout TEXT,
            area_sqm REAL,
            updated_at TEXT,
            source_kind TEXT,
            source_url TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS building_summaries (
            building_key TEXT PRIMARY KEY,
            name TEXT,
            raw_name TEXT,
            address TEXT,
            rent_yen_min INTEGER,
            rent_yen_max INTEGER,
            area_sqm_min REAL,
            area_sqm_max REAL,
            layout_types_json TEXT,
            vacancy_count INTEGER,
            last_updated TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()


def insert_raw_source(conn: sqlite3.Connection, provider: str, source_kind: str, source_url: str, raw_html: str) -> None:
    conn.execute(
        "INSERT INTO raw_sources(provider, source_kind, source_url, raw_html) VALUES(?, ?, ?, ?)",
        (provider, source_kind, source_url, raw_html),
    )
    conn.commit()


def upsert_listing(conn: sqlite3.Connection, record: ListingRecord) -> None:
    building_key = _building_key(record.name, record.address)
    listing_key = _listing_key(record.source_url, record.room_label)
    conn.execute(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, updated_at, source_kind, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_key) DO UPDATE SET
            building_key=excluded.building_key,
            name=excluded.name,
            address=excluded.address,
            room_label=excluded.room_label,
            rent_yen=excluded.rent_yen,
            maint_yen=excluded.maint_yen,
            layout=excluded.layout,
            area_sqm=excluded.area_sqm,
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
            record.updated_at,
            record.source_kind,
            record.source_url,
        ),
    )
    conn.commit()


def replace_building_summary(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO building_summaries(
            building_key, name, raw_name, address,
            rent_yen_min, rent_yen_max, area_sqm_min, area_sqm_max,
            layout_types_json, vacancy_count, last_updated, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(building_key) DO UPDATE SET
            name=excluded.name,
            raw_name=excluded.raw_name,
            address=excluded.address,
            rent_yen_min=excluded.rent_yen_min,
            rent_yen_max=excluded.rent_yen_max,
            area_sqm_min=excluded.area_sqm_min,
            area_sqm_max=excluded.area_sqm_max,
            layout_types_json=excluded.layout_types_json,
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
            row.get("vacancy_count"),
            row.get("last_updated"),
            row.get("last_updated"),
        ),
    )
    conn.commit()
