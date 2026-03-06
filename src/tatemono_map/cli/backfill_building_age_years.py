from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass

from tatemono_map.util.building_age import age_years_from_built_year_month


@dataclass
class BackfillResult:
    scanned: int
    computed: int
    updated: int
    skipped_invalid: int
    samples: list[tuple[str, str | None, int | None, int]]


def _resolve_columns(conn: sqlite3.Connection) -> tuple[str, str]:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(buildings)").fetchall()}
    id_col = "id" if "id" in cols else ("building_id" if "building_id" in cols else "rowid")
    name_col = "name" if "name" in cols else ("canonical_name" if "canonical_name" in cols else "")
    return id_col, name_col


def _iter_buildings(conn: sqlite3.Connection, *, id_col: str, name_col: str):
    return conn.execute(
        f"""
        SELECT {id_col} AS pk, {name_col or "''"} AS name, built_year_month, age_years
        FROM buildings
        WHERE built_year_month IS NOT NULL AND TRIM(built_year_month) != ''
        ORDER BY {id_col} ASC
        """
    )


def backfill_building_age_years(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    sample_limit: int = 10,
) -> BackfillResult:
    scanned = 0
    computed = 0
    updated = 0
    skipped_invalid = 0
    samples: list[tuple[str, str | None, int | None, int]] = []
    id_col, name_col = _resolve_columns(conn)

    for row in _iter_buildings(conn, id_col=id_col, name_col=name_col):
        scanned += 1
        new_age = age_years_from_built_year_month(row["built_year_month"])
        if new_age is None:
            skipped_invalid += 1
            continue

        computed += 1
        old_age = row["age_years"]
        if old_age != new_age:
            updated += 1
            if len(samples) < sample_limit:
                samples.append((row["name"] or "", row["built_year_month"], old_age, new_age))
            if not dry_run:
                conn.execute(f"UPDATE buildings SET age_years=? WHERE {id_col}=?", (new_age, row["pk"]))

    if not dry_run:
        conn.commit()

    return BackfillResult(
        scanned=scanned,
        computed=computed,
        updated=updated,
        skipped_invalid=skipped_invalid,
        samples=samples,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill buildings.age_years from buildings.built_year_month")
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample-limit", type=int, default=10)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    try:
        result = backfill_building_age_years(conn, dry_run=args.dry_run, sample_limit=max(args.sample_limit, 0))
    finally:
        conn.close()

    print(
        f"scanned={result.scanned} computed={result.computed} updated={result.updated} "
        f"skipped_invalid={result.skipped_invalid} dry_run={args.dry_run}"
    )
    if result.samples:
        print("sample_diffs:")
        for name, built_year_month, old_age, new_age in result.samples:
            print(f"- {name} ({built_year_month}): {old_age} -> {new_age}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
