from pathlib import Path

from tatemono_map.cli.master_import import import_master_csv
from tatemono_map.db.repo import connect

HEADER = "page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block\n"


def _write_master_csv(path: Path, body: str) -> None:
    path.write_text(HEADER + body, encoding="utf-8")


def test_master_import_replace_and_seed_persistence(tmp_path: Path) -> None:
    db_path = tmp_path / "master.sqlite3"
    csv_path = tmp_path / "master.csv"

    _write_master_csv(
        csv_path,
        """
1,seed,,建物A,,東京都A,,,,,,,,[source=a page=1]\n
1,seed,,建物B,,東京都B,,,,,,,,[source=b page=1]\n
1,vacancy,2026/01/01 12:00,建物A,101,東京都A,12.3,0.5,1F,1K,20.5,5,RC,[source=a page=1] block-a-101\n
1,vacancy,2026/01/02 12:00,建物B,201,東京都B,15.0,0.8,2F,1LDK,30.0,8,SRC,[source=b page=1] block-b-201\n
""".replace("\n\n", "\n").lstrip(),
    )

    seed_count, vacancy_count, unique_buildings = import_master_csv(str(db_path), str(csv_path))
    assert seed_count == 2
    assert vacancy_count == 2
    assert unique_buildings == 2

    conn = connect(db_path)
    listings = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
    summaries = conn.execute("SELECT COUNT(*) AS c FROM building_summaries").fetchone()["c"]
    conn.close()
    assert listings > 0
    assert summaries >= 2

    _write_master_csv(
        csv_path,
        """
1,seed,,建物A,,東京都A,,,,,,,,[source=a page=1]\n
1,seed,,建物B,,東京都B,,,,,,,,[source=b page=1]\n
""".replace("\n\n", "\n").lstrip(),
    )
    seed_count2, vacancy_count2, unique_buildings2 = import_master_csv(str(db_path), str(csv_path))
    assert seed_count2 == 2
    assert vacancy_count2 == 0
    assert unique_buildings2 == 2

    conn = connect(db_path)
    listings_after = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
    assert listings_after == 0

    seed_rows = conn.execute(
        "SELECT name, vacancy_count FROM building_summaries WHERE name IN ('建物A', '建物B') ORDER BY name"
    ).fetchall()
    conn.close()

    names = sorted({row["name"] for row in seed_rows})
    assert names == ["建物A", "建物B"]
    assert all(row["vacancy_count"] == 0 for row in seed_rows)
