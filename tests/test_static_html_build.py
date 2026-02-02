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
    return db_path


def _insert_summary(engine, **overrides) -> None:
    payload = {
        "building_key": "sample-01",
        "name": "サンプルビル",
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
