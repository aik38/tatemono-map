from __future__ import annotations

import argparse
import os

from tatemono_map.ingest.manual_ulucks_pdf import import_ulucks_pdf_csv
from tatemono_map.render.build import build_dist


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tatemono_map.cli.ulucks_manual_run",
        description="Run manual ulucks PDF(CSV) pipeline: import -> build",
    )
    parser.add_argument("--csv", required=True, help="Path to manual ulucks PDF CSV")
    parser.add_argument("--db", default=os.getenv("SQLITE_DB_PATH", "data/tatemono_map.sqlite3"))
    parser.add_argument("--output", default="dist")
    parser.add_argument("--source-kind", default="ulucks_pdf")
    parser.add_argument("--source-url", default="manual_pdf")
    parser.add_argument("--no-serve", action="store_true", help="Reserved for PS wrapper compatibility")
    args = parser.parse_args()

    imported = import_ulucks_pdf_csv(
        db_path=args.db,
        csv_path=args.csv,
        source_kind=args.source_kind,
        source_url=args.source_url,
    )
    print(f"imported_listings={imported}")
    build_dist(args.db, args.output)
    print(f"build_output_dir={args.output}")


if __name__ == "__main__":
    main()
