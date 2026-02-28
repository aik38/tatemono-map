from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TableSchema:
    name: str
    ddl: str
    columns: tuple[str, ...]


TABLE_SCHEMAS: tuple[TableSchema, ...] = (
    TableSchema(
        name="buildings",
        ddl="""
        CREATE TABLE IF NOT EXISTS buildings (
            building_id TEXT PRIMARY KEY,
            canonical_name TEXT,
            canonical_address TEXT,
            norm_name TEXT,
            norm_address TEXT,
            google_place_id TEXT,
            google_lat REAL,
            google_lng REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        columns=(
            "building_id",
            "canonical_name",
            "canonical_address",
            "norm_name",
            "norm_address",
            "google_place_id",
            "google_lat",
            "google_lng",
            "created_at",
            "updated_at",
        ),
    ),
    TableSchema(
        name="building_sources",
        ddl="""
        CREATE TABLE IF NOT EXISTS building_sources (
            source TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            building_id TEXT NOT NULL,
            raw_name TEXT,
            raw_address TEXT,
            extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source, evidence_id)
        )
        """,
        columns=("source", "evidence_id", "building_id", "raw_name", "raw_address", "extracted_at"),
    ),
    TableSchema(
        name="raw_sources",
        ddl="""
        CREATE TABLE IF NOT EXISTS raw_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_url TEXT NOT NULL,
            content TEXT NOT NULL,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        columns=("id", "provider", "source_kind", "source_url", "content", "fetched_at"),
    ),
    TableSchema(
        name="listings",
        ddl="""
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
            move_in_date TEXT,
            age_years INTEGER,
            structure TEXT,
            updated_at TEXT,
            source_kind TEXT,
            source_url TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        columns=(
            "id",
            "listing_key",
            "building_key",
            "name",
            "address",
            "room_label",
            "rent_yen",
            "maint_yen",
            "layout",
            "area_sqm",
            "move_in_date",
            "age_years",
            "structure",
            "updated_at",
            "source_kind",
            "source_url",
            "fetched_at",
        ),
    ),
    TableSchema(
        name="raw_units",
        ddl="""
        CREATE TABLE IF NOT EXISTS raw_units (
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
            move_in_date TEXT,
            age_years INTEGER,
            structure TEXT,
            updated_at TEXT,
            source_kind TEXT,
            source_url TEXT,
            management_company TEXT,
            management_phone TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        columns=(
            "id",
            "listing_key",
            "building_key",
            "name",
            "address",
            "room_label",
            "rent_yen",
            "maint_yen",
            "layout",
            "area_sqm",
            "move_in_date",
            "age_years",
            "structure",
            "updated_at",
            "source_kind",
            "source_url",
            "management_company",
            "management_phone",
            "fetched_at",
        ),
    ),
    TableSchema(
        name="building_key_aliases",
        ddl="""
        CREATE TABLE IF NOT EXISTS building_key_aliases (
            alias_key TEXT PRIMARY KEY,
            canonical_key TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        columns=("alias_key", "canonical_key", "created_at", "updated_at"),
    ),
    TableSchema(
        name="building_summaries",
        ddl="""
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
            move_in_dates_json TEXT,
            age_years INTEGER,
            structure TEXT,
            vacancy_count INTEGER,
            last_updated TEXT,
            updated_at TEXT
        )
        """,
        columns=(
            "building_key",
            "name",
            "raw_name",
            "address",
            "rent_yen_min",
            "rent_yen_max",
            "area_sqm_min",
            "area_sqm_max",
            "layout_types_json",
            "move_in_dates_json",
            "age_years",
            "structure",
            "vacancy_count",
            "last_updated",
            "updated_at",
        ),
    ),
)

ADDITIVE_MIGRATION_COLUMNS: dict[str, dict[str, str]] = {
    "listings": {
        "age_years": "INTEGER",
        "structure": "TEXT",
    },
    "raw_units": {
        "age_years": "INTEGER",
        "structure": "TEXT",
    },
    "building_summaries": {
        "age_years": "INTEGER",
        "structure": "TEXT",
    },
}


class SchemaMismatchError(RuntimeError):
    pass


def normalize_db_path(db_path: str | Path) -> Path:
    return Path(db_path).expanduser().resolve()


def ensure_schema(db_path: str | Path) -> Path:
    path = normalize_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        for table in TABLE_SCHEMAS:
            conn.execute(table.ddl)
            info_rows = conn.execute(f"PRAGMA table_info({table.name})").fetchall()
            if not info_rows:
                raise SchemaMismatchError(f"Missing required table: {table.name}")

            actual = {row["name"] for row in info_rows}
            expected = set(table.columns)
            missing = [column for column in table.columns if column not in actual]
            if missing:
                migration_cols = ADDITIVE_MIGRATION_COLUMNS.get(table.name, {})
                migrated = False
                for column in missing:
                    column_type = migration_cols.get(column)
                    if column_type:
                        conn.execute(f"ALTER TABLE {table.name} ADD COLUMN {column} {column_type}")
                        migrated = True
                if migrated:
                    info_rows = conn.execute(f"PRAGMA table_info({table.name})").fetchall()
                    actual = {row["name"] for row in info_rows}

            columns = tuple(row["name"] for row in info_rows)
            if not expected.issubset(actual):
                missing = tuple(column for column in table.columns if column not in actual)
                raise SchemaMismatchError(
                    f"Schema mismatch on {table.name}. missing_required={missing} actual={columns}"
                )
    return path


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]
