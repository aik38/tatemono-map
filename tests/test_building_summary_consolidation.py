import sqlite3
from pathlib import Path

from importlib.util import module_from_spec, spec_from_file_location


MODULE_PATH = Path(__file__).resolve().parents[1] / "tatemono_map" / "ingest" / "ulucks_smartlink.py"
SPEC = spec_from_file_location("ulucks_smartlink_local", MODULE_PATH)
assert SPEC and SPEC.loader
ulucks_smartlink = module_from_spec(SPEC)
SPEC.loader.exec_module(ulucks_smartlink)


DDL = """
CREATE TABLE building_summaries (
    building_key TEXT PRIMARY KEY,
    name TEXT,
    raw_name TEXT,
    address TEXT,
    vacancy_status TEXT,
    listings_count INTEGER,
    layout_types_json TEXT,
    rent_min INTEGER,
    rent_max INTEGER,
    area_min REAL,
    area_max REAL,
    move_in_min TEXT,
    move_in_max TEXT,
    last_updated TEXT,
    updated_at TEXT,
    lat REAL,
    lon REAL,
    rent_yen_min INTEGER,
    rent_yen_max INTEGER,
    area_sqm_min REAL,
    area_sqm_max REAL
);
CREATE TABLE listings (
    listing_key TEXT PRIMARY KEY,
    building_key TEXT,
    name TEXT,
    room_label TEXT,
    address TEXT,
    rent_yen INTEGER,
    fee_yen INTEGER,
    area_sqm REAL,
    layout TEXT,
    move_in TEXT,
    lat REAL,
    lon REAL,
    source_url TEXT,
    fetched_at TEXT
);
"""


def test_consolidate_building_summaries_merges_same_building_key_space():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.execute(
        "INSERT INTO building_summaries (building_key,name,raw_name,address,listings_count,last_updated,updated_at) VALUES (?,?,?,?,?,?,?)",
        ("k1", "フォーレスト中尾", "205: フォーレスト中尾", "東京都新宿区1-2-3", 1, "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO building_summaries (building_key,name,raw_name,address,listings_count,last_updated,updated_at) VALUES (?,?,?,?,?,?,?)",
        ("k2", "フォーレスト中尾", "203: フォーレスト中尾", "東京都 新宿区 1-2-3", 2, "2024-01-02T00:00:00+00:00", "2024-01-02T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO listings (listing_key,building_key,name,address,fetched_at) VALUES (?,?,?,?,?)",
        ("l1", "k1", "フォーレスト中尾", "東京都新宿区1-2-3", "2024-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO listings (listing_key,building_key,name,address,fetched_at) VALUES (?,?,?,?,?)",
        ("l2", "k2", "フォーレスト中尾", "東京都新宿区1-2-3", "2024-01-02T00:00:00+00:00"),
    )

    merged = ulucks_smartlink._consolidate_building_summaries(conn)  # noqa: SLF001
    assert merged == 1

    rows = conn.execute("SELECT building_key, name, address FROM building_summaries").fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "フォーレスト中尾"
    listing_keys = {
        row[0] for row in conn.execute("SELECT building_key FROM listings ORDER BY listing_key").fetchall()
    }
    assert len(listing_keys) == 1


def test_building_key_stable_for_same_name_and_address_variants():
    key_1 = ulucks_smartlink._build_building_key("東京都新宿区1-2-3", "205: フォーレスト中尾", 35.0, 139.0)  # noqa: SLF001
    key_2 = ulucks_smartlink._build_building_key("東京都 新宿区 1-2-3", "203: フォーレスト中尾", 35.1, 139.1)  # noqa: SLF001
    assert key_1 == key_2
