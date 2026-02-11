from pathlib import Path

from tatemono_map.db.repo import connect
from tatemono_map.ingest.smartlink_dom import _bulk_upsert, extract_records
from tatemono_map.normalize.building_summaries import rebuild


def test_extract_records_selects_vacancy_table_fixture():
    html = Path("tests/fixtures/ulucks/smartlink_dom_table.html").read_text(encoding="utf-8")

    records = extract_records("https://example.test/view/smartlink/?page=1", html)

    assert len(records) == 3
    assert records[0].name == "サンプルレジデンスA棟"
    assert records[0].address == "福岡県福岡市中央区天神1-1-1"
    assert records[0].rent_yen == 102000
    assert records[0].layout == "1LDK"
    assert records[0].area_sqm == 42.1
    assert records[0].move_in_date == "即入居"
    assert records[0].updated_at == "2026-01-20"


def test_bulk_upsert_populates_raw_units_and_building_summaries(tmp_path):
    db_path = tmp_path / "smartlink_dom.sqlite3"
    html = Path("tests/fixtures/ulucks/smartlink_dom_table.html").read_text(encoding="utf-8")
    records = extract_records("https://example.test/view/smartlink/?page=1", html)

    upserted = _bulk_upsert(str(db_path), records)
    summary_count = rebuild(str(db_path))

    assert upserted == 3
    assert summary_count == 2

    conn = connect(db_path)
    listing_count = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
    raw_count = conn.execute("SELECT COUNT(*) AS c FROM raw_units").fetchone()["c"]
    conn.close()

    assert listing_count == 3
    assert raw_count == 3
