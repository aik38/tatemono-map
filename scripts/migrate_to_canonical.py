from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from tatemono_map.db.schema import TABLE_SCHEMAS, normalize_db_path


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def migrate_raw_sources(conn: sqlite3.Connection) -> None:
    cols = table_columns(conn, "raw_sources")
    if "provider" in cols:
        return
    if "source_system" not in cols:
        raise RuntimeError("raw_sources table has neither provider nor source_system")

    conn.execute("ALTER TABLE raw_sources RENAME TO raw_sources_legacy")
    raw_schema = next(schema for schema in TABLE_SCHEMAS if schema.name == "raw_sources")
    conn.execute(raw_schema.ddl)
    conn.execute(
        """
        INSERT INTO raw_sources(id, provider, source_kind, source_url, content, fetched_at)
        SELECT id, source_system, source_kind, source_url, content, fetched_at
        FROM raw_sources_legacy
        """
    )
    conn.execute("DROP TABLE raw_sources_legacy")


def recreate_table(conn: sqlite3.Connection, table_name: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    schema = next(schema for schema in TABLE_SCHEMAS if schema.name == table_name)
    conn.execute(schema.ddl)


def migrate(db_path: str | Path) -> Path:
    path = normalize_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        migrate_raw_sources(conn)
        recreate_table(conn, "listings")
        recreate_table(conn, "building_summaries")
        conn.commit()
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate tatemono-map DB to canonical schema")
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    args = parser.parse_args()

    migrated = migrate(args.db_path)
    print(f"migrated_to_canonical={migrated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
