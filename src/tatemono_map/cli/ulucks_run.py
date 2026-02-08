from __future__ import annotations

import argparse
import os

from tatemono_map.db.repo import connect, resolve_db_path
from tatemono_map.db.schema import list_tables
from tatemono_map.ingest.ulucks_smartlink import run as ingest_run
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.parse.smartlink_page import parse_and_upsert
from tatemono_map.render.build import build_dist


def print_audit(db_path: str) -> None:
    conn = connect(db_path)
    try:
        tables = list_tables(conn)
        print(f"AUDIT tables={','.join(tables)}")
        for table in ["raw_sources", "listings", "building_summaries"]:
            count = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            print(f"AUDIT count[{table}]={count}")
        rows = conn.execute(
            "SELECT source_kind, COUNT(*) AS c FROM raw_sources GROUP BY source_kind ORDER BY source_kind"
        ).fetchall()
        for row in rows:
            print(f"AUDIT raw_sources_by_kind[{row['source_kind']}]={row['c']}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tatemono_map.cli.ulucks_run",
        description="Run ulucks smartlink pipeline: ingest -> parse -> build",
    )
    parser.add_argument("--url", required=True, help="Smartlink URL")
    parser.add_argument("--db", default=os.getenv("SQLITE_DB_PATH", "data/tatemono_map.sqlite3"))
    parser.add_argument("--output", default="dist")
    parser.add_argument("--max-items", type=int, default=200)
    args = parser.parse_args()

    normalized_db = resolve_db_path(args.db)
    print(f"DB_PATH={normalized_db}")

    saved_sources = ingest_run(args.url, str(normalized_db), max_items=args.max_items)
    print(f"ingest_saved_sources={saved_sources}")
    parsed_listings = parse_and_upsert(str(normalized_db))
    print(f"parse_upserted_listings={parsed_listings}")
    summarized = rebuild(str(normalized_db))
    print(f"rebuilt_building_summaries={summarized}")
    build_dist(str(normalized_db), args.output)
    print(f"build_output_dir={args.output}")
    print_audit(str(normalized_db))


if __name__ == "__main__":
    main()
