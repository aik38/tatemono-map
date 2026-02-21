from __future__ import annotations

import argparse
import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tatemono_map.cli.master_import import _clean_text, _fallback_updated_at, _parse_area, _parse_man_to_yen
from tatemono_map.db.repo import connect

from .matcher import match_building
from .normalization import normalize_building_input

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

REVIEW_COLUMNS = [
    "source_kind",
    "source_id",
    "name",
    "address",
    "normalized_name",
    "normalized_address",
    "reason",
    "candidate_building_ids",
    "candidate_scores",
]


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


def _to_review_row(
    *,
    source_kind: str,
    source_id: str,
    normalized_name: str,
    normalized_address: str,
    raw_name: str,
    raw_address: str,
    reason: str,
    candidate_ids: list[str],
    candidate_scores: list[float],
) -> dict[str, str]:
    return {
        "source_kind": source_kind,
        "source_id": source_id,
        "name": raw_name,
        "address": raw_address,
        "normalized_name": normalized_name,
        "normalized_address": normalized_address,
        "reason": reason,
        "candidate_building_ids": "|".join(candidate_ids[:3]),
        "candidate_scores": "|".join(str(score) for score in candidate_scores[:3]),
    }


def ingest_master_import_csv(db_path: str, csv_path: str, source: str = "master_import") -> Report:
    conn = connect(db_path)
    report = Report()
    source_url = f"file:{Path(csv_path).name}"
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_dir = Path("tmp/review")
    review_dir.mkdir(parents=True, exist_ok=True)
    new_rows: list[dict[str, str]] = []
    suspect_rows: list[dict[str, str]] = []
    unmatched_rows: list[dict[str, str]] = []

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        got = tuple(reader.fieldnames or ())
        if got not in (MASTER_COLUMNS, MASTER_COLUMNS_LEGACY):
            raise ValueError(f"Unexpected master_import.csv header: {reader.fieldnames}")

        for row in reader:
            category = _clean_text(row.get("category"))
            if category == "seed":
                continue

            normalized = normalize_building_input(_clean_text(row.get("building_name")), _clean_text(row.get("address")))
            evidence_id = _row_evidence_id(row, source_url)
            if not normalized.raw_name and not normalized.raw_address:
                report.unresolved += 1
                unmatched_rows.append(
                    _to_review_row(
                        source_kind=source,
                        source_id=evidence_id,
                        normalized_name=normalized.normalized_name,
                        normalized_address=normalized.normalized_address,
                        raw_name=normalized.raw_name,
                        raw_address=normalized.raw_address,
                        reason="missing_name_and_address",
                        candidate_ids=[],
                        candidate_scores=[],
                    )
                )
                continue

            match = match_building(conn, normalized.normalized_name, normalized.normalized_address)
            building_id = match.building_id

            if not building_id and match.reason == "unmatched":
                building_id = hashlib.sha1(
                    f"{normalized.normalized_name}|{normalized.normalized_address}".encode("utf-8")
                ).hexdigest()[:32]
                before = conn.total_changes
                conn.execute(
                    """
                    INSERT OR IGNORE INTO buildings(
                        building_id, canonical_name, canonical_address,
                        norm_name, norm_address, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        building_id,
                        normalized.raw_name,
                        normalized.raw_address,
                        normalized.normalized_name,
                        normalized.normalized_address,
                    ),
                )
                if conn.total_changes > before:
                    report.newly_added += 1
                new_rows.append(
                    _to_review_row(
                        source_kind=source,
                        source_id=evidence_id,
                        normalized_name=normalized.normalized_name,
                        normalized_address=normalized.normalized_address,
                        raw_name=normalized.raw_name,
                        raw_address=normalized.raw_address,
                        reason="new_building_added",
                        candidate_ids=[],
                        candidate_scores=[],
                    )
                )

            if not building_id:
                report.unresolved += 1
                suspect_rows.append(
                    _to_review_row(
                        source_kind=source,
                        source_id=evidence_id,
                        normalized_name=normalized.normalized_name,
                        normalized_address=normalized.normalized_address,
                        raw_name=normalized.raw_name,
                        raw_address=normalized.raw_address,
                        reason=match.reason,
                        candidate_ids=match.candidate_ids,
                        candidate_scores=match.candidate_scores,
                    )
                )
                unmatched_rows.append(
                    _to_review_row(
                        source_kind=source,
                        source_id=evidence_id,
                        normalized_name=normalized.normalized_name,
                        normalized_address=normalized.normalized_address,
                        raw_name=normalized.raw_name,
                        raw_address=normalized.raw_address,
                        reason="building_id_unresolved",
                        candidate_ids=match.candidate_ids,
                        candidate_scores=match.candidate_scores,
                    )
                )

            if building_id:
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
                    (source, evidence_id, building_id, normalized.raw_name, normalized.raw_address),
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
                    normalized.raw_name,
                    normalized.raw_address,
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
            writer = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(new_rows)

    if suspect_rows:
        out_sus = review_dir / f"suspects_{now}.csv"
        with out_sus.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(suspect_rows)

    if unmatched_rows:
        out_unmatched = review_dir / f"unmatched_listings_{now}.csv"
        with out_unmatched.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(unmatched_rows)

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
