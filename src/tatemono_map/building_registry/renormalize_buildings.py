from __future__ import annotations

import argparse
import sqlite3

from tatemono_map.db.repo import connect

from .normalization import normalize_building_input


def renormalize_buildings(conn: sqlite3.Connection) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT building_id, canonical_name, canonical_address, norm_name, norm_address FROM buildings"
    ).fetchall()
    scanned = 0
    updated = 0
    for row in rows:
        scanned += 1
        source_name = (row["canonical_name"] or row["norm_name"] or "").strip()
        source_address = (row["canonical_address"] or row["norm_address"] or "").strip()
        normalized = normalize_building_input(source_name, source_address)
        if normalized.normalized_name == (row["norm_name"] or "") and normalized.normalized_address == (
            row["norm_address"] or ""
        ):
            continue
        conn.execute(
            """
            UPDATE buildings
            SET norm_name=?,
                norm_address=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE building_id=?
            """,
            (normalized.normalized_name, normalized.normalized_address, row["building_id"]),
        )
        updated += 1
    return scanned, updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-normalize buildings.norm_* using current normalization logic")
    parser.add_argument("--db", default="data/tatemono_map.sqlite3")
    args = parser.parse_args()

    conn = connect(args.db)
    scanned, updated = renormalize_buildings(conn)
    conn.commit()
    conn.close()
    print(f"scanned={scanned} updated={updated}")


if __name__ == "__main__":
    main()

