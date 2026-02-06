from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from tatemono_map.api.database import ensure_building_summaries_table

_DATE_PATTERN = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _extract_move_in_date(value: str | None) -> datetime | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return datetime.fromisoformat(stripped)
    except ValueError:
        pass
    match = _DATE_PATTERN.search(stripped)
    if not match:
        return None
    year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    try:
        return datetime(year=year, month=month, day=day)
    except ValueError:
        return None


def _resolve_db_path(db: str | None) -> Path:
    if db:
        return Path(db).expanduser().resolve()
    env_db = os.getenv("SQLITE_DB_PATH")
    if env_db:
        return Path(env_db).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "tatemono_map.sqlite3"


def aggregate_building_summaries(db: str | None = None) -> int:
    db_path = _resolve_db_path(db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    ensure_building_summaries_table(engine)

    with engine.begin() as conn:
        listings_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='listings'")
        ).first()
        if listings_exists is None:
            conn.execute(text("DELETE FROM building_summaries"))
            return 0

        rows = conn.execute(
            text(
                """
                SELECT
                    building_key,
                    name,
                    address,
                    rent_yen,
                    area_sqm,
                    layout,
                    move_in,
                    lat,
                    lon,
                    COALESCE(updated_at, fetched_at) AS updated_at
                FROM listings
                WHERE building_key IS NOT NULL AND TRIM(building_key) <> ''
                """
            )
        ).mappings().all()

        grouped: dict[str, list[dict]] = {}
        for row in rows:
            building_key = str(row["building_key"]).strip()
            grouped.setdefault(building_key, []).append(dict(row))

        conn.execute(text("DELETE FROM building_summaries"))

        for building_key, listing_rows in grouped.items():
            names = [str(r["name"]).strip() for r in listing_rows if r.get("name")]
            addresses = [str(r["address"]).strip() for r in listing_rows if r.get("address")]
            name = names[0] if names else building_key
            address = addresses[0] if addresses else ""
            layouts = sorted({str(r["layout"]).strip() for r in listing_rows if r.get("layout") and str(r["layout"]).strip()})
            rents = [_as_int(r.get("rent_yen")) for r in listing_rows]
            areas = [_as_float(r.get("area_sqm")) for r in listing_rows]
            rent_values = [v for v in rents if v is not None]
            area_values = [v for v in areas if v is not None]
            move_in_dates = [
                dt for dt in (_extract_move_in_date(r.get("move_in")) for r in listing_rows) if dt is not None
            ]
            updated_candidates = [str(r["updated_at"]) for r in listing_rows if r.get("updated_at")]
            lats = [_as_float(r.get("lat")) for r in listing_rows]
            lons = [_as_float(r.get("lon")) for r in listing_rows]

            move_in_min = min(move_in_dates).date().isoformat() if move_in_dates else None
            lat = next((v for v in lats if v is not None), None)
            lon = next((v for v in lons if v is not None), None)

            payload = {
                "building_key": building_key,
                "name": name,
                "raw_name": name,
                "address": address,
                "vacancy_status": "空室あり",
                "listings_count": len(listing_rows),
                "layout_types_json": json.dumps(layouts, ensure_ascii=False),
                "rent_min": min(rent_values) if rent_values else None,
                "rent_max": max(rent_values) if rent_values else None,
                "area_min": min(area_values) if area_values else None,
                "area_max": max(area_values) if area_values else None,
                "move_in_min": move_in_min,
                "move_in_max": None,
                "last_updated": max(updated_candidates) if updated_candidates else datetime.utcnow().isoformat(),
                "lat": lat,
                "lon": lon,
                "rent_yen_min": min(rent_values) if rent_values else None,
                "rent_yen_max": max(rent_values) if rent_values else None,
                "area_sqm_min": min(area_values) if area_values else None,
                "area_sqm_max": max(area_values) if area_values else None,
            }
            conn.execute(
                text(
                    """
                    INSERT INTO building_summaries (
                        building_key, name, raw_name, address, vacancy_status, listings_count,
                        layout_types_json, rent_min, rent_max, area_min, area_max,
                        move_in_min, move_in_max, last_updated, lat, lon,
                        rent_yen_min, rent_yen_max, area_sqm_min, area_sqm_max
                    ) VALUES (
                        :building_key, :name, :raw_name, :address, :vacancy_status, :listings_count,
                        :layout_types_json, :rent_min, :rent_max, :area_min, :area_max,
                        :move_in_min, :move_in_max, :last_updated, :lat, :lon,
                        :rent_yen_min, :rent_yen_max, :area_sqm_min, :area_sqm_max
                    )
                    """
                ),
                payload,
            )
    return len(grouped)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate unit/listing rows into building_summaries.")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: SQLITE_DB_PATH or data/tatemono_map.sqlite3)")
    args = parser.parse_args(argv)
    aggregate_building_summaries(db=args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
