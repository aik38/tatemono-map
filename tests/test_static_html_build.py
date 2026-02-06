import re
from pathlib import Path

import pytest
from sqlalchemy import text

from tatemono_map.api import database
from tatemono_map.render import build as build_module


def _setup_db(tmp_path, monkeypatch) -> Path:
    db_path = tmp_path / "static.sqlite3"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_path))
    database.reset_engine()
    database.init_db()
    engine = database.get_engine()
    ddl = """
    CREATE TABLE IF NOT EXISTS building_summaries (
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
    )
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
        conn.execute(text("ALTER TABLE building_summaries ADD COLUMN updated_at TEXT"))
        conn.execute(text("UPDATE building_summaries SET updated_at = last_updated WHERE updated_at IS NULL"))
    return db_path


def _insert_summary(engine, **overrides) -> None:
    payload = {
        "building_key": "sample-01",
        "name": "サンプルビル",
        "raw_name": "サンプルビル",
        "address": "東京都千代田区1-2-3",
        "vacancy_status": "空室あり",
        "listings_count": 2,
        "layout_types_json": '["1K"]',
        "rent_min": 50000,
        "rent_max": 70000,
        "area_min": 20.0,
        "area_max": 30.0,
        "move_in_min": "即入居",
        "move_in_max": "要相談",
        "last_updated": "2024-01-01T10:00:00+00:00",
        "updated_at": "2024-01-01T10:00:00+00:00",
        "lat": 35.0,
        "lon": 139.0,
        "rent_yen_min": None,
        "rent_yen_max": None,
        "area_sqm_min": None,
        "area_sqm_max": None,
    }
    payload.update(overrides)
    columns = ", ".join(payload.keys())
    values = ", ".join(f":{key}" for key in payload.keys())
    sql = f"INSERT INTO building_summaries ({columns}) VALUES ({values})"
    with engine.begin() as conn:
        conn.execute(text(sql), payload)


def _create_listings_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS listings (
                    listing_key TEXT PRIMARY KEY,
                    building_key TEXT,
                    name TEXT,
                    room_label TEXT,
                    address TEXT,
                    rent_yen INTEGER,
                    maint_yen INTEGER,
                    fee_yen INTEGER,
                    area_sqm REAL,
                    layout TEXT,
                    move_in TEXT,
                    lat REAL,
                    lon REAL,
                    source_url TEXT,
                    fetched_at TEXT,
                    updated_at TEXT
                )
                """
            )
        )


def _insert_listing(engine, **overrides) -> None:
    payload = {
        "listing_key": "listing-1",
        "building_key": "sample-01",
        "name": "サンプルビル",
        "room_label": "205",
        "address": "東京都千代田区1-2-3",
        "rent_yen": 52000,
        "maint_yen": 3000,
        "fee_yen": 3000,
        "area_sqm": 25.8,
        "layout": "1K",
        "move_in": "即入居",
        "lat": 35.0,
        "lon": 139.0,
        "source_url": "https://example.com/src",
        "fetched_at": "2024-01-02T00:00:00+00:00",
        "updated_at": "2024-01-03T00:00:00+00:00",
    }
    payload.update(overrides)
    columns = ", ".join(payload.keys())
    values = ", ".join(f":{key}" for key in payload.keys())
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO listings ({columns}) VALUES ({values})"), payload)


def test_static_build_outputs_summary_and_last_updated(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)

    output_dir = tmp_path / "dist"
    build_module.build_static_site(output_dir=output_dir)

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    building_html = (output_dir / "b" / "sample-01.html").read_text(encoding="utf-8")

    assert "サンプルビル" in index_html
    assert "最終更新日時" in building_html
    assert "2024-01-01T10:00:00+00:00" in building_html


def test_static_build_rejects_forbidden_content(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine, name="管理会社サンプル")

    with pytest.raises(ValueError, match=re.escape("管理会社")):
        build_module.build_static_site(output_dir=tmp_path / "dist")




def test_static_build_fails_fast_when_room_prefix_remains(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine, name="グランデステーション生田III 205号室")

    with pytest.raises(ValueError, match="room-like prefixes"):
        build_module.build_static_site(output_dir=tmp_path / "dist")


def test_static_build_fails_fast_when_same_name_has_multiple_building_keys(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine, building_key="k1", name="フォーレスト中尾")
    _insert_summary(engine, building_key="k2", name="フォーレスト中尾")

    with pytest.raises(ValueError, match="Duplicate building_key"):
        build_module.build_static_site(output_dir=tmp_path / "dist")

def test_static_build_writes_robots_and_sitemap(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)

    output_dir = tmp_path / "dist"
    build_module.build_static_site(
        output_dir=output_dir,
        site_url="https://example.com/tatemono-map",
    )

    robots_txt = (output_dir / "robots.txt").read_text(encoding="utf-8")
    sitemap_xml = (output_dir / "sitemap.xml").read_text(encoding="utf-8")

    assert "Sitemap: https://example.com/tatemono-map/sitemap.xml" in robots_txt
    assert "<urlset" in sitemap_xml
    assert "https://example.com/tatemono-map/" in sitemap_xml
    assert "https://example.com/tatemono-map/b/sample-01.html" in sitemap_xml


def test_static_build_writes_google_verification_file(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)

    output_dir = tmp_path / "dist"
    filename = "google9e29480048aec8bf.html"
    build_module.build_static_site(
        output_dir=output_dir,
        google_verification_file=filename,
    )

    verification_path = output_dir / filename
    assert verification_path.exists()
    assert (
        verification_path.read_text(encoding="utf-8")
        == f"google-site-verification: {filename}\n"
    )


def test_static_build_uses_address_query_links_for_google_maps(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine, address="東京都千代田区1-2-3", lat=35.1, lon=139.2)

    output_dir = tmp_path / "dist"
    build_module.build_static_site(output_dir=output_dir)

    building_html = (output_dir / "b" / "sample-01.html").read_text(encoding="utf-8")
    assert "Google マップ" in building_html
    assert "地図を開く" in building_html
    assert "maps/search/?api=1&amp;query=%E6%9D%B1%E4%BA%AC%E9%83%BD%E5%8D%83%E4%BB%A3%E7%94%B0%E5%8C%BA1-2-3" in building_html
    assert "ストリートビューを開く" not in building_html


def test_room_summary_grouping_and_building_summary_rendered(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)
    _create_listings_table(engine)
    _insert_listing(engine, listing_key="l1", room_label="101", area_sqm=25.1, rent_yen=52000, maint_yen=3000, fee_yen=3000, layout="1K")
    _insert_listing(engine, listing_key="l2", room_label="205", area_sqm=25.1, rent_yen=52000, maint_yen=3000, fee_yen=3000, layout="1K")
    _insert_listing(engine, listing_key="l3", room_label="302", area_sqm=26.2, rent_yen=54000, maint_yen=2000, fee_yen=2000, layout="1K")

    output_dir = tmp_path / "dist"
    build_module.build_static_site(output_dir=output_dir)

    building_html = (output_dir / "b" / "sample-01.html").read_text(encoding="utf-8")
    assert "空室</b>：3室" in building_html
    assert "最終更新日時" in building_html
    assert "空室サマリー" in building_html
    assert "1K" in building_html
    assert "25.1㎡" in building_html
    assert "52,000円" in building_html
    assert ">2</td>" in building_html


def test_public_building_page_never_exposes_room_or_source_fields(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)
    _create_listings_table(engine)
    _insert_listing(
        engine,
        listing_key="x1",
        room_label="205",
        source_url="https://example.com/private-source",
        name="サンプルビル",
        maint_yen=1500,
        fee_yen=1500,
    )

    output_dir = tmp_path / "dist"
    build_module.build_static_site(output_dir=output_dir)

    building_html = (output_dir / "b" / "sample-01.html").read_text(encoding="utf-8")
    assert "205" not in building_html
    assert "source" not in building_html.lower()
    assert "listing-" not in building_html


def test_vacancy_total_matches_sum_of_vacancy_count(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)
    _create_listings_table(engine)
    _insert_listing(engine, listing_key="v1", layout="1K", area_sqm=25.1, rent_yen=52000, maint_yen=3000, fee_yen=3000)
    _insert_listing(engine, listing_key="v2", layout="1K", area_sqm=25.1, rent_yen=52000, maint_yen=3000, fee_yen=3000)
    _insert_listing(engine, listing_key="v3", layout="2LDK", area_sqm=50.0, rent_yen=120000, maint_yen=5000, fee_yen=5000)

    output_dir = tmp_path / "dist"
    build_module.build_static_site(output_dir=output_dir)

    building_html = (output_dir / "b" / "sample-01.html").read_text(encoding="utf-8")
    total_match = re.search(r"空室</b>：(\d+)室", building_html)
    assert total_match
    vacancy_total = int(total_match.group(1))

    counts = [int(value) for value in re.findall(r"<td>(\d+)</td>\s*</tr>", building_html)]
    assert vacancy_total == sum(counts)


def test_dist_leak_scan_detects_room_number_tokens(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)
    output_dir = tmp_path / "dist"
    build_module.build_static_site(output_dir=output_dir)

    suspicious = output_dir / "b" / "manual.html"
    suspicious.write_text("<html><body>#205</body></html>", encoding="utf-8")

    with pytest.raises(ValueError, match="Public leak scan failed"):
        build_module._scan_dist_for_leaks(output_dir)


def test_dist_leak_scan_allows_timestamps(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)
    output_dir = tmp_path / "dist"
    build_module.build_static_site(output_dir=output_dir)

    timestamp_html = output_dir / "b" / "timestamp.html"
    timestamp_html.write_text("<html><body> 最終更新 08:50:26 </body></html>", encoding="utf-8")

    build_module._scan_dist_for_leaks(output_dir)


def test_dist_leak_scan_detects_room_like_colon_prefix(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)
    output_dir = tmp_path / "dist"
    build_module.build_static_site(output_dir=output_dir)

    suspicious = output_dir / "b" / "room-like-prefix.html"
    suspicious.write_text("<html><body> 205:フォーレスト中尾 </body></html>", encoding="utf-8")

    with pytest.raises(ValueError, match="205:フォーレスト中尾"):
        build_module._scan_dist_for_leaks(output_dir)


def test_static_build_writes_private_output_without_linking_from_public(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine)
    _create_listings_table(engine)
    _insert_listing(engine, listing_key="a", room_label="205", rent_yen=50000, area_sqm=21.0, updated_at=None)

    output_dir = tmp_path / "dist"
    private_dir = tmp_path / "dist_private"
    build_module.build_static_site(output_dir=output_dir, private_output_dir=private_dir)

    public_index = (output_dir / "index.html").read_text(encoding="utf-8")
    private_index = (private_dir / "index.html").read_text(encoding="utf-8")

    assert "dist_private" not in public_index
    assert "room_label" in private_index
    assert "205" in private_index


def test_static_build_uses_lat_lon_query_link_when_address_missing(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    engine = database.get_engine()
    _insert_summary(engine, address="", lat=35.1, lon=139.2)

    output_dir = tmp_path / "dist"
    build_module.build_static_site(output_dir=output_dir)

    building_html = (output_dir / "b" / "sample-01.html").read_text(encoding="utf-8")
    assert "Google マップ" in building_html
    assert "地図を開く" in building_html
    assert "https://www.google.com/maps?q=35.1,139.2" in building_html
