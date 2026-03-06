import sqlite3
from datetime import date

from tatemono_map.normalize.building_age_backfill import backfill_building_age_years
from tatemono_map.util.building_age import age_years_from_built_year_month, built_age_sort_rank


def _prepare_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE buildings(
            building_id TEXT PRIMARY KEY,
            canonical_name TEXT,
            built_year_month TEXT,
            age_years INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO buildings(building_id, canonical_name, built_year_month, age_years) VALUES (?,?,?,?)",
        [
            ("b1", "サンライフ恒見２", "1989-04", 1),
            ("b2", "サンパーク門司港", "2001-05", 1),
            ("b3", "future", "2026-04", 9),
            ("b4", "ok", "2025-01", 7),
            ("b5", "unknown", None, 1),
        ],
    )
    conn.commit()
    conn.close()


def test_backfill_building_age_years_updates_existing_broken_values(tmp_path):
    db = tmp_path / "test.sqlite3"
    _prepare_db(db)

    dry = backfill_building_age_years(str(db), dry_run=True)
    assert dry.scanned == 4
    assert dry.changed == 4

    applied = backfill_building_age_years(str(db), dry_run=False)
    assert applied.scanned == 4
    assert applied.changed == 4

    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT canonical_name, age_years FROM buildings").fetchall())
    conn.close()

    assert rows["サンライフ恒見２"] == 36
    assert rows["サンパーク門司港"] == 24
    assert rows["future"] == 0
    assert rows["ok"] == 1


def test_age_years_and_built_age_sort_rank_rules():
    as_of = date(2026, 3, 1)
    assert age_years_from_built_year_month("1989-04", as_of=as_of) != 1
    assert age_years_from_built_year_month("2001-05", as_of=as_of) != 1
    assert age_years_from_built_year_month("2025-01", as_of=as_of) == 1
    assert age_years_from_built_year_month("2026-03", as_of=as_of) == 0
    assert age_years_from_built_year_month("2026-04", as_of=as_of) == 0

    # 築浅順: future -> 0年 -> 1年 -> unknown
    assert built_age_sort_rank(0, built_year_month="2026-04", as_of=as_of) < built_age_sort_rank(1, built_year_month="2025-01", as_of=as_of)
    assert built_age_sort_rank(0, built_year_month="2026-03", as_of=as_of) < built_age_sort_rank(1, built_year_month="2025-01", as_of=as_of)
