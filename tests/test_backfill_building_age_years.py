from __future__ import annotations

import sqlite3
from datetime import date

from tatemono_map.cli.backfill_building_age_years import backfill_building_age_years
from tatemono_map.util.building_age import age_years_from_built_year_month


def _setup_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE buildings (
            id INTEGER PRIMARY KEY,
            name TEXT,
            built_year_month TEXT,
            age_years INTEGER
        )
        """
    )
    return conn


def test_backfill_overwrites_inconsistent_values() -> None:
    conn = _setup_conn()
    conn.executemany(
        "INSERT INTO buildings(id,name,built_year_month,age_years) VALUES(?,?,?,?)",
        [
            (1, "サンパーク門司港", "2001-05", 1),
            (2, "サンライフ恒見２", "1989-04", 1),
            (3, "エクレール東新町", "2001-02", 1),
            (4, "invalid", "2025-13", 1),
        ],
    )

    # Freeze expectations off helper semantics without monkeypatching runtime clock.
    expected_1 = age_years_from_built_year_month("2001-05")
    expected_2 = age_years_from_built_year_month("1989-04")
    expected_3 = age_years_from_built_year_month("2001-02")

    result = backfill_building_age_years(conn)

    assert result.scanned == 4
    assert result.computed == 3
    assert result.updated == 3
    assert result.skipped_invalid == 1

    rows = conn.execute("SELECT id, age_years FROM buildings ORDER BY id").fetchall()
    assert rows[0]["age_years"] == expected_1
    assert rows[1]["age_years"] == expected_2
    assert rows[2]["age_years"] == expected_3
    assert rows[3]["age_years"] == 1


def test_backfill_dry_run_leaves_values_unchanged() -> None:
    conn = _setup_conn()
    conn.execute("INSERT INTO buildings(id,name,built_year_month,age_years) VALUES(1,'x','2001-05',1)")

    result = backfill_building_age_years(conn, dry_run=True)
    assert result.updated == 1
    assert conn.execute("SELECT age_years FROM buildings WHERE id=1").fetchone()[0] == 1


def test_age_years_future_or_current_month_is_zero() -> None:
    assert age_years_from_built_year_month("2026-03", as_of=date(2026, 3, 1)) == 0
    assert age_years_from_built_year_month("2026-04", as_of=date(2026, 3, 1)) == 0
