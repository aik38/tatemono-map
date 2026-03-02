import sqlite3
from pathlib import Path

import importlib.util

import pytest

from tatemono_map.db.schema import ensure_schema
from tests.conftest import repo_path


def _load_migrate():
    script_path = repo_path("scripts", "migrate_to_canonical.py")
    if not script_path.exists():
        pytest.skip("migration script not present; test skipped", allow_module_level=True)
    spec = importlib.util.spec_from_file_location("migrate_to_canonical", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.migrate


migrate = _load_migrate()


def test_ensure_schema_allows_extra_columns(tmp_path):
    db = tmp_path / "extra.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE raw_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_url TEXT NOT NULL,
                content TEXT NOT NULL,
                fetched_at TEXT,
                legacy_col TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE listings (
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
                updated_at TEXT,
                source_kind TEXT,
                source_url TEXT,
                fetched_at TEXT,
                fee_yen INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE building_summaries (
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
                vacancy_count INTEGER,
                last_updated TEXT,
                updated_at TEXT,
                old_extra TEXT
            )
            """
        )
    ensure_schema(db)


def test_ensure_schema_adds_provider_column_for_raw_sources(tmp_path):
    db = tmp_path / "missing.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE raw_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_kind TEXT NOT NULL,
                source_url TEXT NOT NULL,
                content TEXT NOT NULL,
                fetched_at TEXT
            )
            """
        )
    ensure_schema(db)
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(raw_sources)")}
    assert "provider" in cols


def test_migrate_to_canonical_moves_source_system_and_recreates_tables(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE raw_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_system TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_url TEXT NOT NULL,
                content TEXT NOT NULL,
                fetched_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO raw_sources(source_system, source_kind, source_url, content, fetched_at) VALUES (?, ?, ?, ?, ?)",
            ("ulucks", "smartlink_page", "https://example.test", "<html>ok</html>", "2025-01-01"),
        )
        conn.execute("CREATE TABLE listings (id INTEGER PRIMARY KEY, fee_yen INTEGER)")
        conn.execute("CREATE TABLE building_summaries (building_key TEXT PRIMARY KEY, move_in TEXT)")

    migrate(db)

    with sqlite3.connect(db) as conn:
        raw_cols = [r[1] for r in conn.execute("PRAGMA table_info(raw_sources)")]
        assert "provider" in raw_cols
        assert "source_system" not in raw_cols
        row = conn.execute("SELECT provider, source_kind FROM raw_sources").fetchone()
        assert row == ("ulucks", "smartlink_page")

        listing_cols = [r[1] for r in conn.execute("PRAGMA table_info(listings)")]
        assert "fee_yen" not in listing_cols
        assert "rent_yen" in listing_cols

        summary_cols = [r[1] for r in conn.execute("PRAGMA table_info(building_summaries)")]
        assert "move_in" not in summary_cols
        assert "layout_types_json" in summary_cols
        assert "move_in_dates_json" in summary_cols


def test_ensure_schema_adds_age_and_structure_columns_for_existing_db(tmp_path):
    db = tmp_path / "legacy_cols.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE listings (
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
                updated_at TEXT,
                source_kind TEXT,
                source_url TEXT,
                fetched_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE raw_units (
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
                updated_at TEXT,
                source_kind TEXT,
                source_url TEXT,
                management_company TEXT,
                management_phone TEXT,
                fetched_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE building_summaries (
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
                vacancy_count INTEGER,
                last_updated TEXT,
                updated_at TEXT
            )
            """
        )
    ensure_schema(db)

    with sqlite3.connect(db) as conn:
        listing_cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
        raw_unit_cols = {r[1] for r in conn.execute("PRAGMA table_info(raw_units)")}
        summary_cols = {r[1] for r in conn.execute("PRAGMA table_info(building_summaries)")}

    assert {"age_years", "structure"}.issubset(listing_cols)
    assert {"age_years", "structure"}.issubset(raw_unit_cols)
    assert {"age_years", "structure"}.issubset(summary_cols)


def test_ensure_schema_adds_building_master_columns_for_existing_db(tmp_path):
    db = tmp_path / "legacy_buildings.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE buildings (
                building_id TEXT PRIMARY KEY,
                canonical_name TEXT,
                canonical_address TEXT,
                norm_name TEXT,
                norm_address TEXT,
                google_place_id TEXT,
                google_lat REAL,
                google_lng REAL,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
    ensure_schema(db)

    with sqlite3.connect(db) as conn:
        building_cols = {r[1] for r in conn.execute("PRAGMA table_info(buildings)")}

    assert {"structure", "age_years", "built_year", "availability_raw", "availability_label"}.issubset(building_cols)


def test_ensure_schema_adds_building_sources_columns_for_existing_db(tmp_path):
    db = tmp_path / "legacy_building_sources.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE building_sources (
                source TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                building_id TEXT NOT NULL,
                PRIMARY KEY(source, evidence_id)
            )
            """
        )
    ensure_schema(db)

    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(building_sources)")}

    assert {"raw_name", "raw_address", "extracted_at"}.issubset(cols)
