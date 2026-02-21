from __future__ import annotations

import argparse
import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tatemono_map.cli.master_import import _clean_text, _fallback_updated_at, _parse_area, _parse_man_to_yen
from tatemono_map.db.repo import connect

from .common import fuzzy_score, normalize_address, normalize_name, ward_or_city

MASTER_COLUMNS = (
    "page",
    "category",
    "updated_at",
    "building_name",
    "room",
    "address",
    "rent_man",
    "fee_man",
    "floor",
    "layout",
    "area_sqm",
    "age_years",
    "structure",
    "raw_block",
    "evidence_id",
)
MASTER_COLUMNS_LEGACY = MASTER_COLUMNS[:-1]


@dataclass
class Report:
    buildings_total: int = 0
    newly_added: int = 0
    attached_listings: int = 0
    unresolved: int = 0


def _row_evidence_id(row: dict[str, str], source_url: str) -> str:
    explicit = _clean_text(row.get("evidence_id"))
    if explicit:
        return explicit
    raw = row.get("raw_block") or ""
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{source_url}#r={digest}"


def _listing_key(row: dict[str, str]) -> str:
    material = "|".join(
        [
            _clean_text(row.get("building_name")),
            _clean_text(row.get("room")),
            _clean_text(row.get("address")),
            _clean_text(row.get("updated_at")),
            _clean_text(row.get("raw_block")),
            _clean_text(row.get("evidence_id")),
        ]
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _match_building_id(conn, norm_name: str, norm_address: str, place_id: str, raw_address: str) -> str | None:
    if place_id:
        row = conn.execute("SELECT building_id FROM buildings WHERE google_place_id=?", (place_id,)).fetchone()
        if row:
            return row[0]

    row = conn.execute(
        "SELECT building_id FROM buildings WHERE norm_name=? AND norm_address=?",
        (norm_name, norm_address),
    ).fetchone()
    if row:
        return row[0]

    anchor = ward_or_city(raw_address)
    cands = conn.execute(
        "SELECT building_id, norm_name, norm_address, canonical_address FROM buildings WHERE norm_name <> '' OR norm_address <> ''"
    ).fetchall()
    best_id = None
    best_score = 0.0
    for cand in cands:
        cand_anchor = ward_or_city(cand[3] or cand[2])
        if anchor and cand_anchor and anchor != cand_anchor:
            continue
        score = fuzzy_score(norm_name, norm_address, cand[1] or "", cand[2] or "")
        if score > best_score:
            best_score = score
            best_id = cand[0]

    if best_id and best_score >= 0.95:
        return best_id
    return None


def ingest_master_import_csv(db_path: str, csv_path: str, source: str = "master_import") -> Report:
    conn = connect(db_path)
    report = Report()
    source_url = f"file:{Path(csv_path).name}"
    now = datetime.now().strftime("%Y%m%d")
    review_dir = Path("tmp/manual/review")
    review_dir.mkdir(parents=True, exist_ok=True)
    new_rows: list[dict[str, str]] = []
    suspect_rows: list[dict[str, str]] = []

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        got = tuple(reader.fieldnames or ())
        if got not in (MASTER_COLUMNS, MASTER_COLUMNS_LEGACY):
            raise ValueError(f"Unexpected master_import.csv header: {reader.fieldnames}")

        for row in reader:
            category = _clean_text(row.get("category"))
            if category == "seed":
                continue

            raw_name = _clean_text(row.get("building_name"))
            raw_address = _clean_text(row.get("address"))
            if not raw_name and not raw_address:
                report.unresolved += 1
                continue

            norm_name = normalize_name(raw_name)
            norm_address = normalize_address(raw_address)
            place_id = _clean_text(row.get("google_place_id"))
            building_id = _match_building_id(conn, norm_name, norm_address, place_id, raw_address)

            if not building_id:
                building_id = hashlib.sha1(f"{norm_name}|{norm_address}".encode("utf-8")).hexdigest()[:32]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO buildings(
                        building_id, canonical_name, canonical_address,
                        norm_name, norm_address, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (building_id, raw_name, raw_address, norm_name, norm_address),
                )
                report.newly_added += 1
                new_rows.append({"building_id": building_id, "raw_name": raw_name, "raw_address": raw_address})

            evidence_id = _row_evidence_id(row, source_url)
            conn.execute(
                """
                INSERT INTO building_sources(source, evidence_id, building_id, raw_name, raw_address, extracted_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source, evidence_id) DO UPDATE SET
                  building_id=excluded.building_id,
                  raw_name=excluded.raw_name,
                  raw_address=excluded.raw_address,
                  extracted_at=CURRENT_TIMESTAMP
                """,
                (source, evidence_id, building_id, raw_name, raw_address),
            )

            canonical = conn.execute("SELECT canonical_address FROM buildings WHERE building_id=?", (building_id,)).fetchone()
            if canonical and canonical[0] and ward_or_city(canonical[0]) and ward_or_city(raw_address) and ward_or_city(canonical[0]) != ward_or_city(raw_address):
                suspect_rows.append(
                    {
                        "building_id": building_id,
                        "canonical_address": canonical[0],
                        "raw_address": raw_address,
                        "evidence_id": evidence_id,
                    }
                )

            listing_key = _listing_key(row)
            updated_at = _fallback_updated_at(row.get("updated_at"))
            rent_yen = _parse_man_to_yen(row.get("rent_man"))
            maint_yen = _parse_man_to_yen(row.get("fee_man"))
            layout = _clean_text(row.get("layout")) or None
            area_sqm = _parse_area(row.get("area_sqm"))

            conn.execute(
                """
                INSERT INTO raw_sources(provider, source_kind, source_url, content)
                VALUES (?, ?, ?, ?)
                """,
                (source, "master", source_url, row.get("raw_block") or ""),
            )
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
                    updated_at=excluded.updated_at,
                    source_kind=excluded.source_kind,
                    source_url=excluded.source_url
                """,
                (
                    listing_key,
                    building_id,
                    raw_name,
                    raw_address,
                    _clean_text(row.get("room")),
                    rent_yen,
                    maint_yen,
                    layout,
                    area_sqm,
                    None,
                    updated_at,
                    "master",
                    source_url,
                ),
            )
            report.attached_listings += 1

    report.buildings_total = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    conn.commit()
    conn.close()

    if new_rows:
        out_new = review_dir / f"new_buildings_{now}.csv"
        with out_new.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["building_id", "raw_name", "raw_address"])
            writer.writeheader()
            writer.writerows(new_rows)

    if suspect_rows:
        out_sus = review_dir / f"suspects_{now}.csv"
        with out_sus.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["building_id", "canonical_address", "raw_address", "evidence_id"])
            writer.writeheader()
            writer.writerows(suspect_rows)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest weekly master_import.csv into canonical buildings registry")
    parser.add_argument("--db", default="data/tatemono_map.sqlite3")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--source", default="master_import")
    args = parser.parse_args()

    report = ingest_master_import_csv(args.db, args.csv, source=args.source)
    print(
        " ".join(
            [
                f"buildings_total={report.buildings_total}",
                f"newly_added={report.newly_added}",
                f"attached_listings={report.attached_listings}",
                f"unresolved={report.unresolved}",
            ]
        )
    )


if __name__ == "__main__":
    main()
