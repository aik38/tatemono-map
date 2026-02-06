from __future__ import annotations

import argparse
import os
import re
import sqlite3
from pathlib import Path

ROOM_PREFIX_PATTERN = re.compile(r"^\s*\d{1,4}\s*[:：]\s*")


def resolve_db_path(db_path: str | None) -> Path:
    if db_path:
        return Path(db_path).expanduser().resolve()
    env_path = os.getenv("SQLITE_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "data" / "tatemono_map.sqlite3"


def normalize_building_summaries(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS building_summaries (
                building_key TEXT PRIMARY KEY,
                name TEXT,
                raw_name TEXT
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(building_summaries)")}
        if "raw_name" not in columns:
            conn.execute("ALTER TABLE building_summaries ADD COLUMN raw_name TEXT")

        rows = conn.execute(
            "SELECT building_key, name, raw_name FROM building_summaries"
        ).fetchall()

        updated = 0
        for building_key, name, raw_name in rows:
            if name is None:
                continue
            normalized = ROOM_PREFIX_PATTERN.sub("", str(name)).strip()
            new_raw_name = raw_name if raw_name is not None else name
            if normalized != name or new_raw_name != raw_name:
                conn.execute(
                    """
                    UPDATE building_summaries
                    SET name = ?, raw_name = ?
                    WHERE building_key = ?
                    """,
                    (normalized, new_raw_name, building_key),
                )
                updated += 1

        conn.commit()
        return updated
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize building_summaries.name and preserve source in raw_name"
    )
    parser.add_argument("--db-path", default=None, help="SQLite DB path")
    args = parser.parse_args()

    db_path = resolve_db_path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    updated = normalize_building_summaries(db_path)
    print(f"normalized rows: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
