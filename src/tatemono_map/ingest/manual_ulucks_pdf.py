from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.util.text import normalize_text

CANONICAL_COLUMNS = (
    "building_name",
    "address",
    "layout",
    "rent_man",
    "fee_man",
    "area_sqm",
    "updated_at",
    "structure",
    "age_years",
)


def _hash_key(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_man_to_yen(value: str | None) -> int | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    numeric = cleaned.replace("万円", "").replace(",", "")
    return int(float(numeric) * 10000)


def _parse_float(value: str | None) -> float | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    return float(cleaned)


def _building_key(name: str, address: str, structure: str | None, age_years: str | None) -> str:
    payload = "|".join(
        [
            normalize_text(name),
            normalize_text(address),
            normalize_text(structure or ""),
            normalize_text(age_years or ""),
        ]
    )
    return _hash_key(payload)


def _listing_key(
    building_key: str,
    layout: str | None,
    rent_yen: int | None,
    area_sqm: float | None,
    updated_at: str | None,
    source_kind: str,
    source_url: str,
) -> str:
    payload = "|".join(
        [
            building_key,
            normalize_text(layout or ""),
            str(rent_yen) if rent_yen is not None else "",
            str(area_sqm) if area_sqm is not None else "",
            normalize_text(updated_at or ""),
            source_kind,
            source_url,
        ]
    )
    return _hash_key(payload)


def import_ulucks_pdf_csv(
    db_path: str,
    csv_path: str,
    source_kind: str = "ulucks_pdf",
    source_url: str = "manual_pdf",
) -> int:
    conn = connect(db_path)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_listings_listing_key ON listings(listing_key)")

    imported = 0
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = _clean_text(row.get("building_name")) or ""
            address = _clean_text(row.get("address")) or ""
            if not name and not address:
                continue

            structure = _clean_text(row.get("structure"))
            age_years = _clean_text(row.get("age_years"))
            layout = _clean_text(row.get("layout"))
            updated_at = _clean_text(row.get("updated_at"))
            rent_yen = _parse_man_to_yen(row.get("rent_man"))
            maint_yen = _parse_man_to_yen(row.get("fee_man"))
            area_sqm = _parse_float(row.get("area_sqm"))

            building_key = _building_key(name, address, structure, age_years)
            listing_key = _listing_key(building_key, layout, rent_yen, area_sqm, updated_at, source_kind, source_url)

            conn.execute(
                """
                INSERT INTO listings(
                    listing_key, building_key, name, address, room_label,
                    rent_yen, maint_yen, layout, area_sqm, move_in_date,
                    updated_at, source_kind, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(listing_key) DO UPDATE SET
                    building_key=excluded.building_key,
                    name=excluded.name,
                    address=excluded.address,
                    room_label=excluded.room_label,
                    rent_yen=excluded.rent_yen,
                    maint_yen=excluded.maint_yen,
                    layout=excluded.layout,
                    area_sqm=excluded.area_sqm,
                    move_in_date=excluded.move_in_date,
                    updated_at=excluded.updated_at,
                    source_kind=excluded.source_kind,
                    source_url=excluded.source_url
                """,
                (
                    listing_key,
                    building_key,
                    name,
                    address,
                    # Public safety: room_label is intentionally fixed to NULL for manual PDF route.
                    None,
                    rent_yen,
                    maint_yen,
                    layout,
                    area_sqm,
                    None,
                    updated_at,
                    source_kind,
                    source_url,
                ),
            )
            imported += 1

    conn.commit()
    conn.close()
    rebuild(db_path)
    return imported
