from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tatemono_map.cli.master_import import _clean_text
from tatemono_map.db.repo import connect

from .ingest_master_import import REVIEW_COLUMNS, _to_review_row
from .keys import make_alias_key, make_legacy_alias_key
from .matcher import match_building
from .normalization import normalize_building_input
from .renormalize_buildings import renormalize_buildings

INPUT_REQUIRED_COLUMNS = (
    "building_name",
    "address",
    "evidence_id",
)


@dataclass
class Report:
    rows_total: int = 0
    matched: int = 0
    updated: int = 0
    unresolved: int = 0



def _parse_age_years(value: str | None) -> int | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    try:
        numeric = float(cleaned)
    except ValueError:
        return None
    if numeric < 0:
        return None
    return int(numeric)




def _parse_int(value: str | None) -> int | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    try:
        return int(float(cleaned.replace(",", "")))
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    try:
        return float(cleaned.replace(",", ""))
    except ValueError:
        return None
def _fill_only_sql(column: str, value: str = "?") -> str:
    return f"CASE WHEN {column} IS NULL OR {column} = '' THEN {value} ELSE {column} END"


def ingest_building_facts_csv(
    db_path: str,
    csv_path: str,
    *,
    source: str = "mansion_review_facts",
    merge: str = "fill_only",
) -> Report:
    if merge not in {"fill_only", "overwrite"}:
        raise ValueError(f"Unsupported merge mode: {merge}")

    conn = connect(db_path)
    renormalize_buildings(conn)
    report = Report()

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_dir = Path("tmp/review")
    review_dir.mkdir(parents=True, exist_ok=True)
    suspect_rows: list[dict[str, str]] = []
    unmatched_rows: list[dict[str, str]] = []

    alias_rows = conn.execute("SELECT alias_key, canonical_key FROM building_key_aliases").fetchall()
    alias_map = {row["alias_key"]: row["canonical_key"] for row in alias_rows}

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        got = tuple(reader.fieldnames or ())
        if not set(INPUT_REQUIRED_COLUMNS).issubset(set(got)):
            raise ValueError(f"Unexpected building facts header. got={list(got)} expected_required={list(INPUT_REQUIRED_COLUMNS)}")

        for row in reader:
            report.rows_total += 1
            raw_name = _clean_text(row.get("building_name"))
            raw_address = _clean_text(row.get("address"))
            normalized = normalize_building_input(raw_name, raw_address)
            evidence_id = _clean_text(row.get("evidence_id")) or f"{source}:{report.rows_total}"
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
                alias_key = make_alias_key(normalized.normalized_name, normalized.normalized_address)
                building_id = alias_map.get(alias_key, "")
                if not building_id:
                    building_id = alias_map.get(make_legacy_alias_key(normalized.normalized_name, normalized.normalized_address), "")

            if not building_id:
                report.unresolved += 1
                target = suspect_rows if match.reason != "unmatched" else unmatched_rows
                target.append(
                    _to_review_row(
                        source_kind=source,
                        source_id=evidence_id,
                        normalized_name=normalized.normalized_name,
                        normalized_address=normalized.normalized_address,
                        raw_name=normalized.raw_name,
                        raw_address=normalized.raw_address,
                        reason=match.reason if match.reason != "unmatched" else "unmatched_canonical_building",
                        candidate_ids=match.candidate_ids,
                        candidate_scores=match.candidate_scores,
                    )
                )
                continue

            report.matched += 1
            structure = _clean_text(row.get("structure"))
            age_years = _parse_age_years(row.get("age_years"))
            availability_label = _clean_text(row.get("availability_label"))
            built_year_month = _clean_text(row.get("built_year_month"))
            property_kind = _clean_text(row.get("property_kind"))
            sale_price_yen_min = _parse_int(row.get("sale_price_yen_min"))
            sale_price_yen_max = _parse_int(row.get("sale_price_yen_max"))
            sale_price_yen_avg = _parse_int(row.get("sale_price_yen_avg"))
            sale_area_sqm_min = _parse_float(row.get("sale_area_sqm_min"))
            sale_area_sqm_max = _parse_float(row.get("sale_area_sqm_max"))
            sale_layout_types_json = _clean_text(row.get("sale_layout_types_json"))
            sale_listing_count = _parse_int(row.get("sale_listing_count"))
            avg_rent_yen = _parse_int(row.get("avg_rent_yen"))
            rental_listing_count = _parse_int(row.get("rental_listing_count"))

            if merge == "overwrite":
                conn.execute(
                    """
                    UPDATE buildings
                    SET structure=COALESCE(NULLIF(?, ''), structure),
                        age_years=COALESCE(?, age_years),
                        availability_label=COALESCE(NULLIF(?, ''), availability_label),
                        built_year_month=COALESCE(NULLIF(?, ''), built_year_month),
                        property_kind=COALESCE(NULLIF(?, ''), property_kind),
                        sale_price_yen_min=COALESCE(?, sale_price_yen_min),
                        sale_price_yen_max=COALESCE(?, sale_price_yen_max),
                        sale_price_yen_avg=COALESCE(?, sale_price_yen_avg),
                        sale_area_sqm_min=COALESCE(?, sale_area_sqm_min),
                        sale_area_sqm_max=COALESCE(?, sale_area_sqm_max),
                        sale_layout_types_json=COALESCE(NULLIF(?, ''), sale_layout_types_json),
                        sale_listing_count=COALESCE(?, sale_listing_count),
                        avg_rent_yen=COALESCE(?, avg_rent_yen),
                        rental_listing_count=COALESCE(?, rental_listing_count),
                        updated_at=CURRENT_TIMESTAMP
                    WHERE building_id=?
                    """,
                    (
                        structure, age_years, availability_label, built_year_month, property_kind,
                        sale_price_yen_min, sale_price_yen_max, sale_price_yen_avg,
                        sale_area_sqm_min, sale_area_sqm_max, sale_layout_types_json,
                        sale_listing_count, avg_rent_yen, rental_listing_count, building_id,
                    ),
                )
            else:
                conn.execute(
                    f"""
                    UPDATE buildings
                    SET structure={_fill_only_sql('structure')},
                        age_years=CASE WHEN age_years IS NULL THEN ? ELSE age_years END,
                        availability_label={_fill_only_sql('availability_label')},
                        built_year_month={_fill_only_sql('built_year_month')},
                        property_kind={_fill_only_sql('property_kind')},
                        sale_price_yen_min=CASE WHEN sale_price_yen_min IS NULL THEN ? ELSE sale_price_yen_min END,
                        sale_price_yen_max=CASE WHEN sale_price_yen_max IS NULL THEN ? ELSE sale_price_yen_max END,
                        sale_price_yen_avg=CASE WHEN sale_price_yen_avg IS NULL THEN ? ELSE sale_price_yen_avg END,
                        sale_area_sqm_min=CASE WHEN sale_area_sqm_min IS NULL THEN ? ELSE sale_area_sqm_min END,
                        sale_area_sqm_max=CASE WHEN sale_area_sqm_max IS NULL THEN ? ELSE sale_area_sqm_max END,
                        sale_layout_types_json={_fill_only_sql('sale_layout_types_json')},
                        sale_listing_count=CASE WHEN sale_listing_count IS NULL THEN ? ELSE sale_listing_count END,
                        avg_rent_yen=CASE WHEN avg_rent_yen IS NULL THEN ? ELSE avg_rent_yen END,
                        rental_listing_count=CASE WHEN rental_listing_count IS NULL THEN ? ELSE rental_listing_count END,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE building_id=?
                    """,
                    (
                        structure, age_years, availability_label, built_year_month, property_kind,
                        sale_price_yen_min, sale_price_yen_max, sale_price_yen_avg,
                        sale_area_sqm_min, sale_area_sqm_max, sale_layout_types_json,
                        sale_listing_count, avg_rent_yen, rental_listing_count, building_id,
                    ),
                )

            report.updated += conn.execute("SELECT changes()").fetchone()[0]
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

    if suspect_rows:
        out_sus = review_dir / f"suspects_{now}.csv"
        with out_sus.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(suspect_rows)

    if unmatched_rows:
        out_unmatched = review_dir / f"unmatched_building_facts_{now}.csv"
        with out_unmatched.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(unmatched_rows)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest building facts CSV into canonical buildings")
    parser.add_argument("--db", default="data/tatemono_map.sqlite3")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--source", default="mansion_review_facts")
    parser.add_argument("--merge", default="fill_only", choices=["fill_only", "overwrite"])
    args = parser.parse_args()

    report = ingest_building_facts_csv(args.db, args.csv, source=args.source, merge=args.merge)
    print(
        " ".join(
            [
                f"rows_total={report.rows_total}",
                f"matched={report.matched}",
                f"updated={report.updated}",
                f"unresolved={report.unresolved}",
            ]
        )
    )


if __name__ == "__main__":
    main()
