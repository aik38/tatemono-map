from __future__ import annotations

import argparse
import csv
from pathlib import Path

from tatemono_map.db.repo import connect

from .matcher import match_building
from .keys import make_alias_key
from .normalization import normalize_building_input

UI_EVIDENCE_COLUMNS = ("evidence_url_or_id", "evidence_id", "source_id")


def _pick(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        val = (row.get(key) or "").strip()
        if val:
            return val
    return ""


def seed_from_ui_csv(db_path: str, csv_path: str, source: str = "ui_seed") -> tuple[int, int, int]:
    conn = connect(db_path)
    inserted = 0
    attached = 0
    aliases = 0

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            evidence_id = _pick(row, *UI_EVIDENCE_COLUMNS)
            merge_to = (row.get("merge_to_evidence") or "").strip()
            normalized = normalize_building_input(
                _pick(row, "building_name", "canonical_name", "name"),
                _pick(row, "address", "canonical_address"),
            )
            if not normalized.raw_name and not normalized.raw_address:
                continue

            winner_id = ""
            if merge_to:
                winner = conn.execute(
                    "SELECT building_id FROM building_sources WHERE source=? AND evidence_id=?",
                    (source, merge_to),
                ).fetchone()
                if winner:
                    winner_id = winner[0]

            alias_key = make_alias_key(normalized.normalized_name, normalized.normalized_address)
            match = match_building(conn, normalized.normalized_name, normalized.normalized_address)
            building_id = winner_id or match.building_id or alias_key
            existing = conn.execute("SELECT 1 FROM buildings WHERE building_id=?", (building_id,)).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO buildings(
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
                inserted += 1
            else:
                conn.execute(
                    """
                    UPDATE buildings
                    SET norm_name=COALESCE(NULLIF(norm_name, ''), ?),
                        norm_address=COALESCE(NULLIF(norm_address, ''), ?),
                        updated_at=CURRENT_TIMESTAMP
                    WHERE building_id=?
                    """,
                    (normalized.normalized_name, normalized.normalized_address, building_id),
                )

            if winner_id and alias_key != winner_id:
                conn.execute(
                    """
                    INSERT INTO building_key_aliases(alias_key, canonical_key, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(alias_key) DO UPDATE SET
                        canonical_key=excluded.canonical_key,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (alias_key, winner_id),
                )
                aliases += 1

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
                    (source, evidence_id, building_id, normalized.raw_name, normalized.raw_address),
                )
                attached += 1

    conn.commit()
    conn.close()
    return inserted, attached, aliases


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed canonical buildings from reviewed UI CSV")
    parser.add_argument("--db", default="data/tatemono_map.sqlite3")
    parser.add_argument("--csv", default="tmp/manual/inputs/buildings_seed_ui.csv")
    parser.add_argument("--source", default="ui_seed")
    args = parser.parse_args()

    inserted, attached, aliases = seed_from_ui_csv(args.db, args.csv, source=args.source)
    print(f"inserted_buildings={inserted} attached_sources={attached} aliases={aliases}")


if __name__ == "__main__":
    main()
