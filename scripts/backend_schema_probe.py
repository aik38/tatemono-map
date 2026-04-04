from __future__ import annotations

import argparse
import sqlite3


TARGET_TABLES = (
    "buildings",
    "building_sources",
    "building_key_aliases",
    "listings",
    "sale_listings",
    "building_summaries",
    "building_rental_summaries",
    "building_sale_summaries",
    "raw_sources",
    "raw_units",
    "source_priority",
)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def print_table_layout(conn: sqlite3.Connection) -> None:
    for table in TARGET_TABLES:
        if not table_exists(conn, table):
            print(f"{table}: MISSING")
            continue
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: rows={rows} columns={','.join(columns)}")


def print_mansion_review_coverage(conn: sqlite3.Connection) -> None:
    if table_exists(conn, "raw_sources"):
        print(
            "raw_sources_by_provider:",
            conn.execute(
                "SELECT provider, COUNT(*) AS c FROM raw_sources GROUP BY provider ORDER BY c DESC"
            ).fetchall(),
        )
    if table_exists(conn, "listings"):
        print(
            "listings_by_source_kind:",
            conn.execute(
                "SELECT source_kind, COUNT(*) AS c FROM listings GROUP BY source_kind ORDER BY c DESC"
            ).fetchall(),
        )
    if table_exists(conn, "sale_listings"):
        print(
            "sale_listings_by_source:",
            conn.execute(
                "SELECT source, COUNT(*) AS c FROM sale_listings GROUP BY source ORDER BY c DESC"
            ).fetchall(),
        )
    if table_exists(conn, "buildings"):
        thin = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM buildings
            WHERE property_kind='chintai'
              AND COALESCE(avg_rent_yen, 0) = 0
              AND COALESCE(rental_listing_count, 0) = 0
            """
        ).fetchone()[0]
        print(f"buildings_chintai_without_rental_evidence={thin}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/tatemono_map.sqlite3")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    print(f"db={args.db}")
    print_table_layout(conn)
    print_mansion_review_coverage(conn)
    conn.close()


if __name__ == "__main__":
    main()
