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


def test_master_import_accepts_new_master_import_header_and_derives_file(tmp_path: Path) -> None:
    db_path = tmp_path / "master.sqlite3"
    csv_path = tmp_path / "master_import_new.csv"

    csv_path.write_text(
        '﻿"page","category","updated_at","building_name","room","address","rent_man","fee_man","floor","layout","area_sqm","availability_raw","built_raw","age_years","structure","built_year_month","built_age_years","availability_date","availability_flag_immediate","structure_raw","raw_block","evidence_id"\n'
        '"4","vacancy","2026/01/01 12:00","建物C","303","東京都C","11.1","0.2","3F","1K","21.0","即入","2011年09月築","15","RC","2011-09","15","","1","RC造","block-c-303","pdf:0005_xxx.pdf#p=4#i=3"\n',
        encoding="utf-8",
    )

    seed_count, vacancy_count, unique_buildings = import_master_csv(str(db_path), str(csv_path))
    assert seed_count == 0
    assert vacancy_count == 1
    assert unique_buildings == 1

    conn = connect(db_path)
    listing = conn.execute(
        "SELECT source_url, availability_raw, built_raw, built_year_month, built_age_years, availability_flag_immediate, structure_raw, age_years, structure FROM listings"
    ).fetchone()
    raw_unit = conn.execute("SELECT source_url FROM raw_units").fetchone()
    conn.close()

    assert listing["source_url"] == "0005_xxx.pdf"
    assert raw_unit["source_url"] == "0005_xxx.pdf"
    assert listing["availability_raw"] == "即入"
    assert listing["built_raw"] == "2011年09月築"
    assert listing["built_year_month"] == "2011-09"
    assert listing["built_age_years"] == 15
    assert listing["availability_flag_immediate"] == 1
    assert listing["structure_raw"] == "RC造"
    assert listing["age_years"] == 15
    assert listing["structure"] == "RC"


def test_master_import_merges_duplicate_listing_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "master.sqlite3"
    csv_path = tmp_path / "master.csv"

    _write_master_csv(
        csv_path,
        """
1,vacancy,2026/01/01 12:00,建物D,401,東京都D,10.0,,4F,1K,22.0,,,[dup-key]\n
1,vacancy,2026/01/02 12:00,建物D,401,東京都D,,0.3,4F,,22.0,8,RC,[dup-key]\n
""".replace("\n\n", "\n").lstrip(),
    )

    seed_count, vacancy_count, unique_buildings = import_master_csv(str(db_path), str(csv_path))
    assert seed_count == 0
    assert vacancy_count == 2
    assert unique_buildings == 1

    conn = connect(db_path)
    listing_count = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
    listing = conn.execute(
        """
        SELECT rent_yen, maint_yen, layout, age_years, structure, updated_at
        FROM listings
        """
    ).fetchone()
    conn.close()

    assert listing_count == 1
    assert listing["rent_yen"] == 100000
    assert listing["maint_yen"] == 3000
    assert listing["layout"] == "1K"
    assert listing["age_years"] == 8
    assert listing["structure"] == "RC"
    assert listing["updated_at"] == "2026/01/02 12:00"
