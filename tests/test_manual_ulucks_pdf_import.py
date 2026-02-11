from pathlib import Path

from tatemono_map.db.repo import connect
from tatemono_map.ingest.manual_ulucks_pdf import import_ulucks_pdf_csv


def test_import_manual_ulucks_pdf_csv(tmp_path: Path) -> None:
    db_path = tmp_path / "manual.sqlite3"
    csv_path = Path("tests/fixtures/manual/ulucks_pdf_raw_min.csv")

    imported = import_ulucks_pdf_csv(str(db_path), str(csv_path))

    conn = connect(db_path)
    listing_count = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
    summary_count = conn.execute("SELECT COUNT(*) AS c FROM building_summaries").fetchone()["c"]
    row = conn.execute("SELECT room_label, rent_yen, maint_yen FROM listings").fetchone()
    conn.close()

    assert imported > 0
    assert listing_count > 0
    assert summary_count > 0
    assert row["room_label"] is None
    assert row["rent_yen"] == 123000
    assert row["maint_yen"] == 5000
