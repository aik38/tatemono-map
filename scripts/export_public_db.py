#!/usr/bin/env python3
"""Export public-only SQLite database for static site generation."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def export_public_db(src: Path, dst: Path) -> int:
    if not src.exists():
        raise FileNotFoundError(f"source DB not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(src) as src_conn:
        src_conn.row_factory = sqlite3.Row
        table_exists = src_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='building_summaries'"
        ).fetchone()
        if table_exists is None:
            raise RuntimeError("building_summaries table not found in source DB")

        rows = src_conn.execute("SELECT * FROM building_summaries").fetchall()
        schema = src_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='building_summaries'"
        ).fetchone()
        if schema is None or not schema[0]:
            raise RuntimeError("failed to read schema for building_summaries")

    if dst.exists():
        dst.unlink()

    with sqlite3.connect(dst) as dst_conn:
        dst_conn.execute(schema[0])
        if rows:
            columns = rows[0].keys()
            placeholders = ", ".join("?" for _ in columns)
            col_csv = ", ".join(f'"{col}"' for col in columns)
            dst_conn.executemany(
                f"INSERT INTO building_summaries ({col_csv}) VALUES ({placeholders})",
                [tuple(row[col] for col in columns) for row in rows],
            )
        dst_conn.commit()

        count = dst_conn.execute("SELECT COUNT(*) FROM building_summaries").fetchone()[0]

    if count == 0:
        raise RuntimeError("exported public DB has zero rows in building_summaries")

    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default="data/tatemono_map.sqlite3", help="source SQLite DB path")
    parser.add_argument("--dst", default="data/public/public.sqlite3", help="destination SQLite DB path")
    args = parser.parse_args()

    count = export_public_db(Path(args.src), Path(args.dst))
    print(f"Exported {count} rows to {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
