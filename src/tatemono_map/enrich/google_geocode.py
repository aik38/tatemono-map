from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import requests


def _init_cache(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache (
            query TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            lat REAL,
            lng REAL,
            formatted_address TEXT,
            payload_json TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _cache_get(conn: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT query, status, lat, lng, formatted_address, payload_json FROM geocode_cache WHERE query = ?",
        (query,),
    ).fetchone()
    if not row:
        return None
    return {
        "query": row[0],
        "status": row[1],
        "lat": row[2],
        "lng": row[3],
        "formatted_address": row[4],
        "payload_json": row[5],
    }


def _cache_put(conn: sqlite3.Connection, query: str, status: str, payload: dict[str, Any]) -> None:
    result = payload.get("results", [{}])[0] if payload.get("results") else {}
    lat = result.get("geometry", {}).get("location", {}).get("lat")
    lng = result.get("geometry", {}).get("location", {}).get("lng")
    formatted = result.get("formatted_address")
    conn.execute(
        """
        INSERT INTO geocode_cache(query, status, lat, lng, formatted_address, payload_json, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(query) DO UPDATE SET
          status=excluded.status,
          lat=excluded.lat,
          lng=excluded.lng,
          formatted_address=excluded.formatted_address,
          payload_json=excluded.payload_json,
          updated_at=datetime('now')
        """,
        (query, status, lat, lng, formatted, json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()


def _should_geocode(row: dict[str, str], force_all: bool) -> bool:
    if force_all:
        return True
    normalized = (row.get("normalized_address") or "").strip()
    return not normalized or "-" not in normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich buildings_master.csv with Google Geocoding API")
    parser.add_argument("--in", dest="input_csv", required=True)
    parser.add_argument("--out", dest="output_csv", required=True)
    parser.add_argument("--cache", default="tmp/cache/google_geocode.sqlite")
    parser.add_argument("--qps", type=float, default=5.0)
    parser.add_argument("--force-all", action="store_true")
    args = parser.parse_args()

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is required")

    input_path = Path(args.input_csv)
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = _init_cache(Path(args.cache))

    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("input csv header missing")
        fieldnames = list(reader.fieldnames)
        for col in ["geocode_status", "geocode_lat", "geocode_lng", "geocode_formatted_address", "geocode_cache_hit"]:
            if col not in fieldnames:
                fieldnames.append(col)
        rows = [{k: (v or "") for k, v in row.items()} for row in reader]

    interval = 1.0 / max(args.qps, 0.1)
    last_call = 0.0

    for row in rows:
        query = (row.get("address") or "").strip()
        if not query or not _should_geocode(row, force_all=args.force_all):
            row["geocode_status"] = row.get("geocode_status", "")
            continue

        cached = _cache_get(conn, query)
        if cached:
            row["geocode_status"] = cached["status"]
            row["geocode_lat"] = cached["lat"] or ""
            row["geocode_lng"] = cached["lng"] or ""
            row["geocode_formatted_address"] = cached["formatted_address"] or ""
            row["geocode_cache_hit"] = "true"
            continue

        wait = interval - (time.time() - last_call)
        if wait > 0:
            time.sleep(wait)

        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": query, "key": api_key, "language": "ja", "region": "jp"},
            timeout=20,
        )
        last_call = time.time()
        resp.raise_for_status()
        payload = resp.json()
        status = payload.get("status", "UNKNOWN")
        _cache_put(conn, query, status, payload)

        result = payload.get("results", [{}])[0] if payload.get("results") else {}
        loc = result.get("geometry", {}).get("location", {})
        row["geocode_status"] = status
        row["geocode_lat"] = loc.get("lat", "")
        row["geocode_lng"] = loc.get("lng", "")
        row["geocode_formatted_address"] = result.get("formatted_address", "")
        row["geocode_cache_hit"] = "false"

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    conn.close()
    print(f"[DONE] {output_path}")


if __name__ == "__main__":
    main()
