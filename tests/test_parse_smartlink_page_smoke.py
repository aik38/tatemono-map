from pathlib import Path

from tatemono_map.db.repo import connect, insert_raw_source
from tatemono_map.parse.smartlink_page import parse_and_upsert


def test_parse_smartlink_page_creates_listings(tmp_path):
    db = tmp_path / "test.sqlite3"
    html = Path("tests/fixtures/ulucks/smartlink_phase_a_page_1.html").read_text(encoding="utf-8")

    conn = connect(db)
    insert_raw_source(conn, "ulucks", "smartlink_page", "https://example.test/smartlink?page=1", html)
    conn.close()

    parsed = parse_and_upsert(str(db))
    assert parsed >= 1

    conn = connect(db)
    count = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
    conn.close()
    assert count >= 1
