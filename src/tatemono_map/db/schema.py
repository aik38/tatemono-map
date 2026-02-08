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
            "updated_at",
            "source_kind",
            "source_url",
            "fetched_at",
        ),
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
            "vacancy_count",
            "last_updated",
            "updated_at",
        ),
    ),
)


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
            columns = tuple(row["name"] for row in info_rows)
            expected = set(table.columns)
            actual = set(columns)
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
