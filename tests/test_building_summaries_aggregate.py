import json

from sqlalchemy import text

from tatemono_map.aggregate.building_summaries import aggregate_building_summaries
from tatemono_map.api import database


def _setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "aggregate.sqlite3"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_path))
    database.reset_engine()
    database.init_db()
    engine = database.get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS listings (
                    listing_key TEXT PRIMARY KEY,
                    building_key TEXT,
                    name TEXT,
                    address TEXT,
                    rent_yen INTEGER,
                    area_sqm REAL,
                    layout TEXT,
                    move_in TEXT,
                    lat REAL,
                    lon REAL,
                    fetched_at TEXT,
                    updated_at TEXT
                )
                """
            )
        )
    return db_path, engine


def test_aggregate_building_summaries_from_listings(tmp_path, monkeypatch):
    db_path, engine = _setup_db(tmp_path, monkeypatch)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO listings (listing_key,building_key,name,address,rent_yen,area_sqm,layout,move_in,lat,lon,fetched_at,updated_at)
                VALUES
                ('l1','b-1','テストマンション','822-0002 福岡県直方市',50000,20.5,'1K','2026-05-01',33.1,130.1,'2026-01-01T00:00:00','2026-01-01T00:00:00'),
                ('l2','b-1','テストマンション','822-0002 福岡県直方市',70000,25.5,'1LDK','2026-04-01',33.1,130.1,'2026-01-01T00:00:00','2026-01-02T00:00:00'),
                ('l3','b-1','テストマンション','822-0002 福岡県直方市',65000,22.0,'1K',NULL,33.1,130.1,'2026-01-01T00:00:00','2026-01-03T00:00:00')
                """
            )
        )

    count = aggregate_building_summaries(db=str(db_path))
    assert count == 1

    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM building_summaries WHERE building_key='b-1'"))\
            .mappings().one()

    assert row["name"] == "テストマンション"
    assert row["rent_min"] == 50000
    assert row["rent_max"] == 70000
    assert row["area_min"] == 20.5
    assert row["area_max"] == 25.5
    assert row["move_in_min"] == "2026-04-01"
    assert row["move_in_max"] is None
    assert row["listings_count"] == 3
    assert json.loads(row["layout_types_json"]) == ["1K", "1LDK"]
