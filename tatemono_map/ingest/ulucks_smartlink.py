# tatemono_map/ingest/ulucks_smartlink.py
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


FORBIDDEN_PUBLIC_PATTERNS = [
    re.compile(r"号室"),
    re.compile(r"参照元"),
    re.compile(r"元付"),
    re.compile(r"管理会社"),
    re.compile(r"見積"),
    re.compile(r"\.pdf\b", re.IGNORECASE),
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\bURL\b", re.IGNORECASE),
]


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for attr, value in attrs:
            if attr.lower() == "href" and value:
                self.links.append(value)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if cleaned:
            self._chunks.append(cleaned)

    def text(self) -> str:
        return "\n".join(self._chunks)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_db_path(db_arg: str | None) -> Path:
    if db_arg:
        return Path(db_arg).expanduser().resolve()
    env_path = os.getenv("SQLITE_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "data" / "tatemono_map.sqlite3"


def _ensure_parent_dir(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_system TEXT,
            source_kind TEXT,
            source_url TEXT,
            fetched_at TEXT,
            content TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            listing_key TEXT PRIMARY KEY,
            building_key TEXT,
            name TEXT,
            address TEXT,
            rent_yen INTEGER,
            fee_yen INTEGER,
            area_sqm REAL,
            layout TEXT,
            move_in TEXT,
            source_url TEXT,
            fetched_at TEXT
        )
        """
    )
    conn.execute(
        """
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
    )
    required_columns = {
        "name": "TEXT",
        "address": "TEXT",
        "vacancy_status": "TEXT",
        "listings_count": "INTEGER",
        "layout_types_json": "TEXT",
        "rent_min": "INTEGER",
        "rent_max": "INTEGER",
        "area_min": "REAL",
        "area_max": "REAL",
        "move_in_min": "TEXT",
        "move_in_max": "TEXT",
        "last_updated": "TEXT",
        "lat": "REAL",
        "lon": "REAL",
        "rent_yen_min": "INTEGER",
        "rent_yen_max": "INTEGER",
        "area_sqm_min": "REAL",
        "area_sqm_max": "REAL",
    }
    existing_columns = _table_columns(conn, "building_summaries")
    for column, column_type in required_columns.items():
        if column not in existing_columns:
            conn.execute(
                f"ALTER TABLE building_summaries ADD COLUMN {column} {column_type}"
            )


def _fetch_url(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "tatemono-map/ulucks-poc"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read()
    return content.decode("utf-8", errors="replace")


def _save_raw_source(
    conn: sqlite3.Connection,
    *,
    source_system: str,
    source_kind: str,
    source_url: str,
    content: str,
) -> None:
    conn.execute(
        """
        INSERT INTO raw_sources (source_system, source_kind, source_url, fetched_at, content)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source_system, source_kind, source_url, _utc_iso(), content),
    )


def _extract_links(base_url: str, html_text: str) -> list[str]:
    parser = _LinkExtractor()
    parser.feed(html_text)
    links: list[str] = []
    for link in parser.links:
        absolute = urllib.parse.urljoin(base_url, link)
        links.append(absolute)
    seen: set[str] = set()
    filtered: list[str] = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        if "smartview" in link or "smart" in link:
            filtered.append(link)
    return filtered


def _sanitize_public_field(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    for pattern in FORBIDDEN_PUBLIC_PATTERNS:
        if pattern.search(normalized):
            return None
    return normalized


def _normalize_building_name(value: str | None) -> str:
    sanitized = _sanitize_public_field(value)
    return sanitized or "（名称未設定）"


def _normalize_address(value: str | None) -> str:
    sanitized = _sanitize_public_field(value)
    return sanitized or ""


def _normalize_key_component(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _build_building_key(address: str, name: str) -> str:
    source = f"{_normalize_key_component(address)}|{_normalize_key_component(name)}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _parse_money(value: str) -> int | None:
    cleaned = value.replace(",", "").strip()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*万円", cleaned)
    if match:
        return int(float(match.group(1)) * 10000)
    match = re.search(r"([0-9]+)", cleaned)
    if match:
        return int(match.group(1))
    return None


def _parse_area(value: str) -> float | None:
    cleaned = value.replace(",", "").strip()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", cleaned)
    if match:
        return float(match.group(1))
    return None


def _extract_field(lines: list[str], labels: list[str]) -> str | None:
    for line in lines:
        for label in labels:
            pattern = rf"{re.escape(label)}\s*[:：]\s*(.+)"
            match = re.search(pattern, line)
            if match:
                return match.group(1).strip()
    return None


def _extract_listing_fields(source_url: str, html_text: str) -> dict[str, Any]:
    title_match = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    title = html.unescape(title_match.group(1)).strip() if title_match else None
    parser = _TextExtractor()
    parser.feed(html_text)
    text = parser.text()
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    name = _extract_field(lines, ["建物名", "物件名"]) or title
    address = _extract_field(lines, ["住所", "所在地"]) or None
    rent_raw = _extract_field(lines, ["家賃", "賃料"])
    fee_raw = _extract_field(lines, ["共益費", "管理費"])
    area_raw = _extract_field(lines, ["面積", "専有面積"])
    layout = _extract_field(lines, ["間取り"])
    move_in = _extract_field(lines, ["入居可能日", "入居時期"])

    return {
        "name": _normalize_building_name(name),
        "address": _normalize_address(address),
        "rent_yen": _parse_money(rent_raw or ""),
        "fee_yen": _parse_money(fee_raw or ""),
        "area_sqm": _parse_area(area_raw or ""),
        "layout": _sanitize_public_field(layout),
        "move_in": _sanitize_public_field(move_in),
        "source_url": source_url,
    }


def _upsert_listing(conn: sqlite3.Connection, listing: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO listings (
            listing_key,
            building_key,
            name,
            address,
            rent_yen,
            fee_yen,
            area_sqm,
            layout,
            move_in,
            source_url,
            fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_key) DO UPDATE SET
            building_key=excluded.building_key,
            name=excluded.name,
            address=excluded.address,
            rent_yen=excluded.rent_yen,
            fee_yen=excluded.fee_yen,
            area_sqm=excluded.area_sqm,
            layout=excluded.layout,
            move_in=excluded.move_in,
            source_url=excluded.source_url,
            fetched_at=excluded.fetched_at
        """,
        (
            listing["listing_key"],
            listing["building_key"],
            listing["name"],
            listing["address"],
            listing["rent_yen"],
            listing["fee_yen"],
            listing["area_sqm"],
            listing["layout"],
            listing["move_in"],
            listing["source_url"],
            listing["fetched_at"],
        ),
    )


def _aggregate_buildings(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT building_key, name, address, rent_yen, area_sqm, layout, move_in
        FROM listings
        WHERE building_key IS NOT NULL
        """
    ).fetchall()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        building_key = row[0]
        name = row[1] or "（名称未設定）"
        address = row[2] or ""
        entry = grouped.setdefault(
            building_key,
            {
                "building_key": building_key,
                "name": name,
                "address": address,
                "rents": [],
                "areas": [],
                "layouts": set(),
                "move_ins": [],
            },
        )
        rent = row[3]
        if rent is not None:
            entry["rents"].append(rent)
        area = row[4]
        if area is not None:
            entry["areas"].append(area)
        layout = row[5]
        if layout:
            entry["layouts"].add(layout)
        move_in = row[6]
        if move_in:
            entry["move_ins"].append(move_in)

    now = _utc_iso()
    for entry in grouped.values():
        rents = entry["rents"]
        areas = entry["areas"]
        move_ins = sorted(set(entry["move_ins"]))
        layout_types = sorted(entry["layouts"])
        listings_count = max(len(rents), len(areas), len(layout_types), len(move_ins))
        vacancy_status = "空室あり" if listings_count > 0 else "満室"

        conn.execute(
            """
            INSERT INTO building_summaries (
                building_key,
                name,
                address,
                vacancy_status,
                listings_count,
                layout_types_json,
                rent_min,
                rent_max,
                area_min,
                area_max,
                move_in_min,
                move_in_max,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(building_key) DO UPDATE SET
                name=excluded.name,
                address=excluded.address,
                vacancy_status=excluded.vacancy_status,
                listings_count=excluded.listings_count,
                layout_types_json=excluded.layout_types_json,
                rent_min=excluded.rent_min,
                rent_max=excluded.rent_max,
                area_min=excluded.area_min,
                area_max=excluded.area_max,
                move_in_min=excluded.move_in_min,
                move_in_max=excluded.move_in_max,
                last_updated=excluded.last_updated
            """,
            (
                entry["building_key"],
                _normalize_building_name(entry["name"]),
                _normalize_address(entry["address"]),
                vacancy_status,
                listings_count,
                json.dumps(layout_types, ensure_ascii=False),
                min(rents) if rents else None,
                max(rents) if rents else None,
                min(areas) if areas else None,
                max(areas) if areas else None,
                move_ins[0] if move_ins else None,
                move_ins[-1] if move_ins else None,
                now,
            ),
        )


def ingest_ulucks_smartlink(url: str, limit: int, db_path: Path) -> None:
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        _ensure_tables(conn)

        smartlink_html = _fetch_url(url)
        _save_raw_source(
            conn,
            source_system="ulucks",
            source_kind="smartlink",
            source_url=url,
            content=smartlink_html,
        )

        candidate_links = _extract_links(url, smartlink_html)
        for link in candidate_links[:limit]:
            try:
                detail_html = _fetch_url(link)
            except urllib.error.URLError:
                continue
            _save_raw_source(
                conn,
                source_system="ulucks",
                source_kind="smartview",
                source_url=link,
                content=detail_html,
            )
            extracted = _extract_listing_fields(link, detail_html)
            building_key = _build_building_key(
                extracted["address"],
                extracted["name"],
            )
            listing_key = hashlib.sha256(link.encode("utf-8")).hexdigest()
            listing = {
                **extracted,
                "building_key": building_key,
                "listing_key": listing_key,
                "fetched_at": _utc_iso(),
            }
            _upsert_listing(conn, listing)

        _aggregate_buildings(conn)
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Ulucks smartlink pages into SQLite.")
    parser.add_argument("--url", required=True, help="Smartlink URL to ingest")
    parser.add_argument("--limit", type=int, default=10, help="Max smartview pages to fetch")
    parser.add_argument("--db", default=None, help="Path to SQLite DB (SQLITE_DB_PATH)")
    args = parser.parse_args()

    ingest_ulucks_smartlink(args.url, args.limit, _resolve_db_path(args.db))


if __name__ == "__main__":
    main()
