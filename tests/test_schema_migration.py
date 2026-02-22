import sqlite3
from pathlib import Path

import importlib.util

import pytest

from tatemono_map.db.schema import SchemaMismatchError, ensure_schema
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


def test_ensure_schema_fails_when_required_columns_missing(tmp_path):
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
    try:
        ensure_schema(db)
        assert False, "SchemaMismatchError was expected"
    except SchemaMismatchError as e:
        assert "missing_required" in str(e)


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
