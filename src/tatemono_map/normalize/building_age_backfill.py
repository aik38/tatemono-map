from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from tatemono_map.util.building_age import age_years_from_built_year_month


@dataclass(frozen=True)
class BackfillResult:
    scanned: int
    changed: int


def backfill_building_age_years(db_path: str, *, dry_run: bool = False) -> BackfillResult:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                building_id,
                built_year_month,
                age_years
            FROM buildings
            WHERE built_year_month IS NOT NULL
              AND TRIM(built_year_month) <> ''
            """
        ).fetchall()

        updates: list[tuple[int | None, str]] = []
        for row in rows:
            building_id = str(row["building_id"])
            expected_age = age_years_from_built_year_month(row["built_year_month"])
            if expected_age != row["age_years"]:
                updates.append((expected_age, building_id))

        if updates and not dry_run:
            conn.executemany("UPDATE buildings SET age_years = ? WHERE building_id = ?", updates)
            conn.commit()

        return BackfillResult(scanned=len(rows), changed=len(updates))
    finally:
        conn.close()

