# tatemono_map/ingest/ulucks_smartlink.py
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import unicodedata
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

SMARTLINK_ERROR_HINT = (
    "smartlink が期限切れ、または link_id が無効の可能性があります。"
    " ブラウザで当該 URL を開いてリストが表示できるか確認してください。"
    " 表示できない場合は、ログイン状態で smartlink を再生成してください。"
)


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
        )
        """
    )
    conn.execute(
        """
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
        "raw_name": "TEXT",
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
        "updated_at": "TEXT",
    }
    existing_columns = _table_columns(conn, "building_summaries")
    for column, column_type in required_columns.items():
        if column not in existing_columns:
            conn.execute(
                f"ALTER TABLE building_summaries ADD COLUMN {column} {column_type}"
            )
    listing_required_columns = {
        "room_label": "TEXT",
        "lat": "REAL",
        "lon": "REAL",
    }
    listing_existing_columns = _table_columns(conn, "listings")
    for column, column_type in listing_required_columns.items():
        if column not in listing_existing_columns:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {column} {column_type}")


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


def _extract_anchor_links(base_url: str, html_text: str) -> list[str]:
    parser = _LinkExtractor()
    parser.feed(html_text)
    links: list[str] = []
    for link in parser.links:
        links.append(urllib.parse.urljoin(base_url, link))
    return links


def _extract_regex_links(base_url: str, html_text: str) -> list[str]:
    links: list[str] = []
    full_urls = re.findall(
        r"https?://[^\s\"'<>]*smartview[^\s\"'<>]*",
        html_text,
        flags=re.IGNORECASE,
    )
    links.extend(full_urls)
    relative_urls = re.findall(
        r"/view/smartview/[^\s\"'<>]+",
        html_text,
        flags=re.IGNORECASE,
    )
    links.extend(urllib.parse.urljoin(base_url, rel) for rel in relative_urls)
    return links


def _extract_urls_from_json(obj: Any, found: list[str]) -> None:
    if isinstance(obj, dict):
        for value in obj.values():
            _extract_urls_from_json(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _extract_urls_from_json(item, found)
    elif isinstance(obj, str):
        if "smartview" in obj or "/view/smartview/" in obj:
            found.append(obj)


def _extract_script_links(base_url: str, html_text: str) -> list[str]:
    scripts = re.findall(
        r"<script[^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    found: list[str] = []
    for script in scripts:
        found.extend(
            re.findall(
                r"https?://[^\s\"'<>]+",
                script,
                flags=re.IGNORECASE,
            )
        )
        found.extend(
            re.findall(
                r"/view/smartview/[^\s\"'<>]+",
                script,
                flags=re.IGNORECASE,
            )
        )
        for match in re.findall(r"['\"]([^'\"]+)['\"]", script):
            if "smartview" in match or "/view/smartview/" in match:
                found.append(match)
        stripped = script.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                _extract_urls_from_json(parsed, found)
    return [urllib.parse.urljoin(base_url, link) for link in found]


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if not url:
            continue
        normalized = url.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _filter_detail_urls(urls: list[str]) -> list[str]:
    return [url for url in urls if "smartview" in url or "/view/smartview/" in url]


def _detect_meta_refresh(html_text: str) -> str | None:
    match = re.search(
        r"<meta[^>]+http-equiv=[\"']?refresh[\"']?[^>]*content=[\"']([^\"']+)[\"']",
        html_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    content = match.group(1)
    parts = [part.strip() for part in content.split(";") if part.strip()]
    for part in parts:
        if part.lower().startswith("url="):
            return part.split("=", 1)[1].strip(" '\"")
    if parts:
        return parts[-1]
    return None


def _detect_js_redirect(html_text: str) -> str | None:
    patterns = [
        r"(?:window\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]",
        r"(?:window\.)?location\.replace\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"(?:window\.)?location\.assign\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _detect_smartlink_error_reason(html_text: str) -> str | None:
    normalized_html = html_text.lower()
    parser = _TextExtractor()
    parser.feed(html_text)
    normalized_text = parser.text().lower()

    direct_markers = [
        "このリストは存在しません",
        "ログインして再表示",
        "ulucksユーザーはログインして再表示",
    ]
    for marker in direct_markers:
        if marker in html_text or marker in normalized_text:
            return marker

    error_section_markers = ["flashmessage", "error", "alert", "c-message"]
    generic_error_text_markers = ["存在しません", "ログイン", "期限", "無効"]
    if any(marker in normalized_html for marker in error_section_markers):
        if any(marker in normalized_text for marker in generic_error_text_markers):
            return "flash/error 領域にエラーメッセージ"

    return None


def _validate_smartlink_html_or_raise(html_text: str, source_url: str) -> None:
    reason = _detect_smartlink_error_reason(html_text)
    if reason is None:
        return
    raise RuntimeError(
        f"Smartlink error page detected ({reason}) for: {source_url}. {SMARTLINK_ERROR_HINT}"
    )


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
    if not sanitized:
        return "（名称未設定）"
    normalized = unicodedata.normalize("NFKC", sanitized)
    normalized = re.sub(r"^\s*\d+\s*[:：]\s*", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or "（名称未設定）"


def _normalize_address(value: str | None) -> str:
    sanitized = _sanitize_public_field(value)
    if not sanitized:
        return ""
    normalized = unicodedata.normalize("NFKC", sanitized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _normalize_address_for_match(value: str | None) -> str:
    normalized = _normalize_address(value)
    normalized = re.sub(r"[‐‑‒–—―ーｰ−]", "-", normalized)
    normalized = re.sub(r"[\s、,。\.\-]", "", normalized)
    return normalized.lower()


def _normalize_key_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("　", " ")
    normalized = re.sub(r"^\s*\d+\s*[:：]\s*", "", normalized)
    normalized = re.sub(r"[‐‑‒–—―ーｰ−]", "-", normalized)
    normalized = re.sub(r"[、,。.]", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.lower().strip()


def _build_building_key(address: str, name: str, lat: float | None, lon: float | None) -> str:
    del lat, lon
    source = f"{_normalize_key_component(name)}|{_normalize_key_component(address)}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _extract_room_label(name: str | None, lines: list[str]) -> tuple[str | None, str | None]:
    room = _extract_field(lines, ["号室", "部屋番号", "室番号"]) or None
    if room:
        room = unicodedata.normalize("NFKC", room).strip()
    if not name:
        return None, room
    normalized_name = unicodedata.normalize("NFKC", name).strip()
    match = re.match(r"^\s*(\d+[A-Za-z]?)\s*[:：]\s*(.+)$", normalized_name)
    if match:
        return match.group(2).strip(), room or match.group(1)
    return normalized_name, room


def _parse_lat_lon(lines: list[str]) -> tuple[float | None, float | None]:
    lat = _parse_area(_extract_field(lines, ["緯度", "lat", "LAT"]) or "")
    lon = _parse_area(_extract_field(lines, ["経度", "lng", "lon", "LNG", "LON"]) or "")
    return lat, lon


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

    raw_name = _extract_field(lines, ["建物名", "物件名"]) or title
    name, room_label = _extract_room_label(raw_name, lines)
    address = _extract_field(lines, ["住所", "所在地"]) or None
    rent_raw = _extract_field(lines, ["家賃", "賃料"])
    fee_raw = _extract_field(lines, ["共益費", "管理費"])
    area_raw = _extract_field(lines, ["面積", "専有面積"])
    layout = _extract_field(lines, ["間取り"])
    move_in = _extract_field(lines, ["入居可能日", "入居時期"])
    lat, lon = _parse_lat_lon(lines)

    return {
        "name": _normalize_building_name(name),
        "room_label": room_label,
        "address": _normalize_address(address),
        "rent_yen": _parse_money(rent_raw or ""),
        "fee_yen": _parse_money(fee_raw or ""),
        "area_sqm": _parse_area(area_raw or ""),
        "layout": _sanitize_public_field(layout),
        "move_in": _sanitize_public_field(move_in),
        "lat": lat,
        "lon": lon,
        "source_url": source_url,
    }


def _upsert_listing(conn: sqlite3.Connection, listing: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO listings (
            listing_key,
            building_key,
            name,
            room_label,
            address,
            rent_yen,
            fee_yen,
            area_sqm,
            layout,
            move_in,
            lat,
            lon,
            source_url,
            fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_key) DO UPDATE SET
            building_key=excluded.building_key,
            name=excluded.name,
            room_label=excluded.room_label,
            address=excluded.address,
            rent_yen=excluded.rent_yen,
            fee_yen=excluded.fee_yen,
            area_sqm=excluded.area_sqm,
            layout=excluded.layout,
            move_in=excluded.move_in,
            lat=excluded.lat,
            lon=excluded.lon,
            source_url=excluded.source_url,
            fetched_at=excluded.fetched_at
        """,
        (
            listing["listing_key"],
            listing["building_key"],
            listing["name"],
            listing["room_label"],
            listing["address"],
            listing["rent_yen"],
            listing["fee_yen"],
            listing["area_sqm"],
            listing["layout"],
            listing["move_in"],
            listing["lat"],
            listing["lon"],
            listing["source_url"],
            listing["fetched_at"],
        ),
    )


def _choose_canonical_key(rows: list[sqlite3.Row]) -> str:
    def _priority(row: sqlite3.Row) -> tuple[int, int, int, str]:
        has_address = 0 if _normalize_address(row["address"]) else 1
        last_updated = str(row["last_updated"] or "")
        listing_count = -(int(row["listings_count"] or 0))
        return (has_address, -len(last_updated), listing_count, str(row["building_key"]))

    return str(min(rows, key=_priority)["building_key"])


def _consolidate_building_summaries(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT building_key, name, raw_name, address, last_updated, updated_at, listings_count
        FROM building_summaries
        WHERE name IS NOT NULL
        """
    ).fetchall()

    grouped_by_name: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        name_key = _normalize_key_component(str(row["name"] or ""))
        grouped_by_name.setdefault(name_key, []).append(row)

    merged_rows = 0
    for same_name_rows in grouped_by_name.values():
        if len(same_name_rows) <= 1:
            continue

        has_any_address = any(_normalize_address(row["address"]) for row in same_name_rows)
        grouped_by_address: dict[str, list[sqlite3.Row]] = {}
        for row in same_name_rows:
            address_key = (
                _normalize_address_for_match(row["address"]) if has_any_address else ""
            )
            grouped_by_address.setdefault(address_key, []).append(row)

        for same_building_rows in grouped_by_address.values():
            if len(same_building_rows) <= 1:
                continue

            canonical_key = _choose_canonical_key(same_building_rows)
            canonical_row = next(
                row for row in same_building_rows if str(row["building_key"]) == canonical_key
            )
            canonical_raw = canonical_row["raw_name"] or canonical_row["name"]
            canonical_address = _normalize_address(canonical_row["address"])
            canonical_updated = canonical_row["updated_at"] or canonical_row["last_updated"]

            for duplicate_row in same_building_rows:
                duplicate_key = str(duplicate_row["building_key"])
                if duplicate_key == canonical_key:
                    continue
                merged_rows += 1
                conn.execute(
                    "UPDATE listings SET building_key = ? WHERE building_key = ?",
                    (canonical_key, duplicate_key),
                )
                if not canonical_address and _normalize_address(duplicate_row["address"]):
                    canonical_address = _normalize_address(duplicate_row["address"])
                if not canonical_raw and (duplicate_row["raw_name"] or duplicate_row["name"]):
                    canonical_raw = duplicate_row["raw_name"] or duplicate_row["name"]
                duplicate_updated = duplicate_row["updated_at"] or duplicate_row["last_updated"]
                if duplicate_updated and (
                    not canonical_updated or str(duplicate_updated) > str(canonical_updated)
                ):
                    canonical_updated = duplicate_updated
                conn.execute(
                    "DELETE FROM building_summaries WHERE building_key = ?",
                    (duplicate_key,),
                )

            conn.execute(
                """
                UPDATE building_summaries
                SET raw_name = ?,
                    address = CASE WHEN address IS NULL OR TRIM(address) = '' THEN ? ELSE address END,
                    updated_at = COALESCE(?, updated_at, last_updated)
                WHERE building_key = ?
                """,
                (canonical_raw, canonical_address, canonical_updated, canonical_key),
            )

    return merged_rows


def _aggregate_buildings(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT building_key, name, address, rent_yen, area_sqm, layout, move_in, fetched_at, lat, lon
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
                "raw_name": name,
                "address": address,
                "rents": [],
                "areas": [],
                "layouts": set(),
                "move_ins": [],
                "updated_at": [],
                "lat_lon": [],
                "count": 0,
            },
        )
        entry["count"] += 1
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
        updated = row[7]
        if updated:
            entry["updated_at"].append(updated)
        if row[8] is not None and row[9] is not None:
            entry["lat_lon"].append((row[8], row[9]))

    for entry in grouped.values():
        rents = entry["rents"]
        areas = entry["areas"]
        move_ins = sorted(set(entry["move_ins"]))
        layout_types = sorted(entry["layouts"])
        listings_count = entry["count"]
        vacancy_status = "空室あり" if listings_count > 0 else "不明"
        last_updated = max(entry["updated_at"]) if entry["updated_at"] else _utc_iso()
        lat = entry["lat_lon"][0][0] if entry["lat_lon"] else None
        lon = entry["lat_lon"][0][1] if entry["lat_lon"] else None

        conn.execute(
            """
            INSERT INTO building_summaries (
                building_key,
                name,
                raw_name,
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
                last_updated,
                updated_at,
                rent_yen_min,
                rent_yen_max,
                area_sqm_min,
                area_sqm_max,
                lat,
                lon
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(building_key) DO UPDATE SET
                name=excluded.name,
                raw_name=excluded.raw_name,
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
                last_updated=excluded.last_updated,
                updated_at=excluded.updated_at,
                rent_yen_min=excluded.rent_yen_min,
                rent_yen_max=excluded.rent_yen_max,
                area_sqm_min=excluded.area_sqm_min,
                area_sqm_max=excluded.area_sqm_max,
                lat=COALESCE(excluded.lat, building_summaries.lat),
                lon=COALESCE(excluded.lon, building_summaries.lon)
            """,
            (
                entry["building_key"],
                _normalize_building_name(entry["name"]),
                entry["name"],
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
                last_updated,
                last_updated,
                min(rents) if rents else None,
                max(rents) if rents else None,
                min(areas) if areas else None,
                max(areas) if areas else None,
                lat,
                lon,
            ),
        )

    _consolidate_building_summaries(conn)


def ingest_ulucks_smartlink(url: str, limit: int, db_path: Path, fail_when_empty: bool = False) -> None:
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        _ensure_tables(conn)

        smartlink_html = _fetch_url(url)
        print(f"Fetched smartlink bytes: {len(smartlink_html.encode('utf-8'))}")
        _save_raw_source(
            conn,
            source_system="ulucks",
            source_kind="smartlink",
            source_url=url,
            content=smartlink_html,
        )
        _validate_smartlink_html_or_raise(smartlink_html, url)

        effective_url = url
        redirect_type: str | None = None
        redirect_target = _detect_meta_refresh(smartlink_html)
        if redirect_target:
            redirect_type = "meta-refresh"
        else:
            redirect_target = _detect_js_redirect(smartlink_html)
            if redirect_target:
                redirect_type = "js-redirect"
        if redirect_target:
            effective_url = urllib.parse.urljoin(url, redirect_target)
            print(f"Detected redirect ({redirect_type}): {redirect_target} -> {effective_url}")
            smartlink_html = _fetch_url(effective_url)
            print(
                f"Fetched effective smartlink bytes: {len(smartlink_html.encode('utf-8'))}"
            )
            _save_raw_source(
                conn,
                source_system="ulucks",
                source_kind="smartlink_effective",
                source_url=effective_url,
                content=smartlink_html,
            )
            _validate_smartlink_html_or_raise(smartlink_html, effective_url)
        else:
            print("No redirect detected in smartlink HTML.")

        href_links = _extract_anchor_links(effective_url, smartlink_html)
        regex_links = _extract_regex_links(effective_url, smartlink_html)
        script_links = _extract_script_links(effective_url, smartlink_html)
        print(f"Extracted href links: {len(href_links)}")
        print(f"Extracted regex links: {len(regex_links)}")
        print(f"Extracted script links: {len(script_links)}")

        candidate_links = _dedupe_urls(href_links + regex_links + script_links)
        detail_urls = _filter_detail_urls(candidate_links)
        detail_urls = _dedupe_urls(detail_urls)[:limit]
        print(f"Final detail URLs: {len(detail_urls)}")
        if not detail_urls:
            raise RuntimeError(
                "No detail URLs extracted. Use `python -m tatemono_map.tools.db_inspect "
                "--dump-latest-raw --system ulucks --kind smartlink "
                "--out dist_tmp/tmp_ulucks_smartlink_latest.html` to inspect saved smartlink HTML. "
                f"{SMARTLINK_ERROR_HINT}"
            )

        fetched_details = 0
        upserted_listings = 0
        for link in detail_urls:
            try:
                detail_html = _fetch_url(link)
            except urllib.error.URLError:
                continue
            fetched_details += 1
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
                extracted["lat"],
                extracted["lon"],
            )
            listing_key = hashlib.sha256(link.encode("utf-8")).hexdigest()
            listing = {
                **extracted,
                "building_key": building_key,
                "listing_key": listing_key,
                "fetched_at": _utc_iso(),
            }
            _upsert_listing(conn, listing)
            upserted_listings += 1

        if fail_when_empty and upserted_listings == 0:
            raise RuntimeError(
                "No listings were upserted from smartlink detail pages. "
                f"{SMARTLINK_ERROR_HINT}"
            )

        _aggregate_buildings(conn)
        print(f"Fetched detail pages: {fetched_details}")
        print(f"Upserted listings: {upserted_listings}")
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
    parser.add_argument(
        "--fail",
        action="store_true",
        help="Fail when no listings are upserted (for runbook failure checks)",
    )
    args = parser.parse_args()

    ingest_ulucks_smartlink(
        args.url,
        args.limit,
        _resolve_db_path(args.db),
        fail_when_empty=args.fail,
    )


if __name__ == "__main__":
    main()
