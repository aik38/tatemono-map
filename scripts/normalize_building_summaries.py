from __future__ import annotations

import argparse
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

ROOM_PREFIX_PATTERN = re.compile(r"^\s*\d{1,4}\s*[:：]\s*")


def resolve_db_path(db_path: str | None) -> Path:
    if db_path:
        return Path(db_path).expanduser().resolve()
    env_path = os.getenv("SQLITE_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "data" / "tatemono_map.sqlite3"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _normalize_building_name(value: str | None) -> str:
    if not value:
        return "（名称未設定）"
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = ROOM_PREFIX_PATTERN.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or "（名称未設定）"


def _normalize_address(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _normalize_key_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("　", " ")
    normalized = ROOM_PREFIX_PATTERN.sub("", normalized)
    normalized = re.sub(r"[‐‑‒–—―ーｰ−]", "-", normalized)
    normalized = re.sub(r"[、,。.]", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.lower().strip()


def _normalize_address_for_match(value: str | None) -> str:
    normalized = _normalize_address(value)
    normalized = re.sub(r"[‐‑‒–—―ーｰ−]", "-", normalized)
    normalized = re.sub(r"[\s、,。\.\-]", "", normalized)
    return normalized.lower()


def _choose_canonical_key(rows: list[sqlite3.Row]) -> str:
    def _priority(row: sqlite3.Row) -> tuple[int, int, int, str]:
        has_address = 0 if _normalize_address(row["address"]) else 1
        last_updated = str(row["updated_at"] or row["last_updated"] or "")
        listing_count = -(int(row["listings_count"] or 0))
        return (has_address, -len(last_updated), listing_count, str(row["building_key"]))

    return str(min(rows, key=_priority)["building_key"])


def normalize_building_summaries(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS building_summaries (
                building_key TEXT PRIMARY KEY,
                name TEXT,
                raw_name TEXT,
                address TEXT,
                updated_at TEXT,
                last_updated TEXT,
                listings_count INTEGER
            )
            """
        )
        columns = _table_columns(conn, "building_summaries")
        if "raw_name" not in columns:
            conn.execute("ALTER TABLE building_summaries ADD COLUMN raw_name TEXT")
        if "updated_at" not in columns:
            conn.execute("ALTER TABLE building_summaries ADD COLUMN updated_at TEXT")

        # normalize name/address + preserve raw_name
        rows = conn.execute(
            "SELECT building_key, name, raw_name, address, updated_at, last_updated FROM building_summaries"
        ).fetchall()
        for row in rows:
            normalized_name = _normalize_building_name(row["name"])
            normalized_address = _normalize_address(row["address"])
            raw_name = row["raw_name"] or row["name"]
            updated_at = row["updated_at"] or row["last_updated"]
            conn.execute(
                """
                UPDATE building_summaries
                SET name = ?, raw_name = ?, address = ?, updated_at = ?
                WHERE building_key = ?
                """,
                (normalized_name, raw_name, normalized_address, updated_at, row["building_key"]),
            )

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

        merged = 0
        for same_name_rows in grouped_by_name.values():
            if len(same_name_rows) <= 1:
                continue

            has_any_address = any(_normalize_address(row["address"]) for row in same_name_rows)
            grouped_by_address: dict[str, list[sqlite3.Row]] = {}
            for row in same_name_rows:
                address_key = _normalize_address_for_match(row["address"]) if has_any_address else ""
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
                    merged += 1
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

        conn.commit()
        return merged
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize and consolidate building_summaries into one row per building"
    )
    parser.add_argument("--db-path", default=None, help="SQLite DB path")
    args = parser.parse_args()

    db_path = resolve_db_path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    merged = normalize_building_summaries(db_path)
    print(f"merged rows: {merged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
