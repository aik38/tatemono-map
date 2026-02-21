from __future__ import annotations

import argparse
import csv
import uuid
from pathlib import Path

from tatemono_map.db.repo import connect

from .common import normalize_address, normalize_name


UI_EVIDENCE_COLUMNS = ("evidence_url_or_id", "evidence_id", "source_id")


def _pick(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        val = (row.get(key) or "").strip()
        if val:
            return val
    return ""


def _deterministic_building_id(norm_name: str, norm_address: str) -> str:
    material = f"{norm_name}|{norm_address}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, material))


def seed_from_ui_csv(db_path: str, csv_path: str, source: str = "ui_seed") -> tuple[int, int]:
    conn = connect(db_path)
    inserted = 0
    attached = 0

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_name = _pick(row, "building_name", "canonical_name", "name")
            raw_address = _pick(row, "address", "canonical_address")
            evidence_id = _pick(row, *UI_EVIDENCE_COLUMNS)
            merge_to = (row.get("merge_to_evidence") or "").strip()
            if not raw_name and not raw_address:
                continue

            norm_name = normalize_name(raw_name)
            norm_address = normalize_address(raw_address)

            winner_id = ""
            if merge_to:
                winner = conn.execute(
                    "SELECT building_id FROM building_sources WHERE source=? AND evidence_id=?",
                    (source, merge_to),
                ).fetchone()
                if winner:
                    winner_id = winner[0]

            building_id = winner_id or _deterministic_building_id(norm_name, norm_address)
            existing = conn.execute("SELECT 1 FROM buildings WHERE building_id=?", (building_id,)).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO buildings(
                        building_id, canonical_name, canonical_address,
                        norm_name, norm_address, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (building_id, raw_name, raw_address, norm_name, norm_address),
                )
                inserted += 1

            if evidence_id:
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
                attached += 1

    conn.commit()
    conn.close()
    return inserted, attached


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed canonical buildings from reviewed UI CSV")
    parser.add_argument("--db", default="data/tatemono_map.sqlite3")
    parser.add_argument("--csv", default="tmp/manual/inputs/buildings_seed_ui.csv")
    parser.add_argument("--source", default="ui_seed")
    args = parser.parse_args()

    inserted, attached = seed_from_ui_csv(args.db, args.csv, source=args.source)
    print(f"inserted_buildings={inserted} attached_sources={attached}")


if __name__ == "__main__":
    main()
