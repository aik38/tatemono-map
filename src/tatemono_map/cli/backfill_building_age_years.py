from __future__ import annotations

import argparse

from tatemono_map.normalize.building_age_backfill import backfill_building_age_years


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill buildings.age_years from built_year_month")
    parser.add_argument("--db", required=True, help="Path to sqlite3")
    parser.add_argument("--dry-run", action="store_true", help="Show changed rows count without writing")
    args = parser.parse_args()

    result = backfill_building_age_years(args.db, dry_run=args.dry_run)
    mode = "dry-run" if args.dry_run else "applied"
    print(f"[{mode}] scanned={result.scanned} changed={result.changed}")


if __name__ == "__main__":
    main()
