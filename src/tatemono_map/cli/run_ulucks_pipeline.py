from __future__ import annotations

import argparse
import os

from tatemono_map.ingest.ulucks_smartlink import run as ingest_run
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.parse.smartlink_page import parse_and_upsert
from tatemono_map.render.build import build_dist


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--db-path", default=os.getenv("SQLITE_DB_PATH", "data/tatemono_map.sqlite3"))
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--max-items", type=int, default=200)
    args = parser.parse_args()

    ingest_run(args.url, args.db_path, max_items=args.max_items)
    parse_and_upsert(args.db_path)
    rebuild(args.db_path)
    build_dist(args.db_path, args.output_dir)
    print("pipeline completed")


if __name__ == "__main__":
    main()
