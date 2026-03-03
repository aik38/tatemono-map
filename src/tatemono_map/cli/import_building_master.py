from __future__ import annotations

import argparse
import csv
from pathlib import Path

from tatemono_map.building_registry.keys import make_alias_key
from tatemono_map.building_registry.normalization import normalize_building_input
from tatemono_map.db.repo import connect


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _parse_int(v: str | None) -> int | None:
    text = _clean(v)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def run(db_path: str, csv_path: str, source: str) -> tuple[int, int]:
    conn = connect(db_path)
    created = 0
    updated = 0

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for idx, row in enumerate(reader, start=1):
            normalized = normalize_building_input(_clean(row.get("building_name") or row.get("name")), _clean(row.get("address")))
            if not normalized.raw_name and not normalized.raw_address:
                continue

            building_id = make_alias_key(normalized.normalized_name, normalized.normalized_address)
            existing = conn.execute("SELECT 1 FROM buildings WHERE building_id=?", (building_id,)).fetchone()
            structure = _clean(row.get("structure")) or None
            age_years = _parse_int(row.get("age_years"))
            built_year = _parse_int(row.get("built_year"))
            availability_raw = _clean(row.get("availability_raw")) or None
            availability_label = _clean(row.get("availability_label")) or None

            if existing:
                conn.execute(
                    """
                    UPDATE buildings
                       SET canonical_name=COALESCE(NULLIF(?, ''), canonical_name),
                           canonical_address=COALESCE(NULLIF(?, ''), canonical_address),
                           structure=COALESCE(NULLIF(?, ''), structure),
                           age_years=COALESCE(?, age_years),
                           built_year=COALESCE(?, built_year),
                           availability_raw=COALESCE(NULLIF(?, ''), availability_raw),
                           availability_label=COALESCE(NULLIF(?, ''), availability_label),
                           norm_name=COALESCE(NULLIF(norm_name, ''), ?),
                           norm_address=COALESCE(NULLIF(norm_address, ''), ?),
                           updated_at=CURRENT_TIMESTAMP
                     WHERE building_id=?
                    """,
                    (
                        normalized.raw_name,
                        normalized.canonical_address,
                        structure,
                        age_years,
                        built_year,
                        availability_raw,
                        availability_label,
                        normalized.normalized_name,
                        normalized.normalized_address,
                        building_id,
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO buildings(
                        building_id, canonical_name, canonical_address,
                        structure, age_years, built_year, availability_raw, availability_label,
                        norm_name, norm_address, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        building_id,
                        normalized.raw_name,
                        normalized.canonical_address,
                        structure,
                        age_years,
                        built_year,
                        availability_raw,
                        availability_label,
                        normalized.normalized_name,
                        normalized.normalized_address,
                    ),
                )
                created += 1

            evidence_id = _clean(row.get("evidence_id")) or f"{Path(csv_path).name}#{idx}"
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

    conn.commit()
    conn.close()
    return created, updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/tatemono_map.sqlite3")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--source", default="building_master")
    args = parser.parse_args()
    created, updated = run(args.db, args.csv, args.source)
    print(f"created={created} updated={updated}")


if __name__ == "__main__":
    main()
