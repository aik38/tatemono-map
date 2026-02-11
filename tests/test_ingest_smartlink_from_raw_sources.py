from pathlib import Path

from tatemono_map.db.repo import connect, insert_raw_source
from tatemono_map.ingest.smartlink_from_raw_sources import ingest


def test_ingest_uses_detail_url_to_avoid_page_level_collisions(tmp_path):
    db = tmp_path / "test.sqlite3"
    html = """
    <html><body>
      <article class="property-card">
        <h3><a href="/view/smartlink_page/unit-a/">サンプルタワー</a></h3>
        <div>所在地: 東京都新宿区1-1-1</div>
        <div>賃料: 10万</div>
        <div>専有面積: 25.0㎡</div>
        <div>間取り: 1K</div>
      </article>
      <article class="property-card">
        <h3><a href="/view/smartlink_page/unit-b/">サンプルタワー</a></h3>
        <div>所在地: 東京都新宿区1-1-1</div>
        <div>賃料: 11万</div>
        <div>専有面積: 27.0㎡</div>
        <div>間取り: 1DK</div>
      </article>
    </body></html>
    """

    conn = connect(db)
    insert_raw_source(conn, "ulucks", "smartlink_page", "https://example.test/smartlink?page=1", html)
    conn.close()

    upserted, summary_count = ingest(str(db))

    assert upserted == 2
    assert summary_count >= 1

    conn = connect(db)
    listings_count = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
    raw_units_count = conn.execute("SELECT COUNT(*) AS c FROM raw_units").fetchone()["c"]
    source_urls = conn.execute("SELECT source_url FROM listings ORDER BY source_url").fetchall()
    conn.close()

    assert listings_count == 2
    assert raw_units_count == 2
    assert [row["source_url"] for row in source_urls] == [
        "https://example.test/view/smartlink_page/unit-a/",
        "https://example.test/view/smartlink_page/unit-b/",
    ]


def test_ingest_from_realistic_fixture_rebuilds_building_summaries(tmp_path):
    db = tmp_path / "test.sqlite3"
    html = Path("tests/fixtures/ulucks/smartlink_phase_a_page_1.html").read_text(encoding="utf-8")

    conn = connect(db)
    insert_raw_source(conn, "ulucks", "smartlink_page", "https://example.test/smartlink?page=1", html)
    conn.close()

    upserted, summary_count = ingest(str(db))

    assert upserted >= 2
    assert summary_count >= 1

    conn = connect(db)
    building_count = conn.execute("SELECT COUNT(*) AS c FROM building_summaries").fetchone()["c"]
    conn.close()
    assert building_count >= 1
