from tests.conftest import repo_path
from tatemono_map.cli.import_building_master import run
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild


def test_import_building_master_routes_feed_building_summaries_zero_vacancy(tmp_path):
    db = tmp_path / "master.sqlite3"

    created_a, updated_a = run(str(db), str(repo_path("tests", "fixtures", "building_master", "mansion_review_master.csv")), "mansion_review")
    created_b, updated_b = run(str(db), str(repo_path("tests", "fixtures", "building_master", "orient_master.csv")), "orient")

    assert created_a == 1
    assert created_b == 1
    assert updated_a == 0
    assert updated_b == 0

    rebuild(str(db))

    conn = connect(db)
    rows = conn.execute(
        """
        SELECT name, vacancy_count, structure, age_years, building_built_year_month, building_availability_label
        FROM building_summaries
        ORDER BY name
        """
    ).fetchall()
    source_rows = conn.execute("SELECT source, COUNT(*) c FROM building_sources GROUP BY source ORDER BY source").fetchall()
    conn.close()

    assert len(rows) == 2
    assert {row["vacancy_count"] for row in rows} == {0}
    assert {row["building_availability_label"] for row in rows} == {None}
    assert {row["structure"] for row in rows} == {"RC", "SRC"}
    assert {row["building_built_year_month"] for row in rows} == {"2008-01", "1995-01"}
    assert [(r["source"], r["c"]) for r in source_rows] == [("mansion_review", 1), ("orient", 1)]
