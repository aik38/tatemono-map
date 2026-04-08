from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tatemono_map.cli.master_import import _clean_text
from tatemono_map.db.repo import connect
from tatemono_map.util.building_age import age_years_from_built_year_month

from .common import insert_unmatched_queue, normalize_source_name, source_domain
from .ingest_master_import import REVIEW_COLUMNS, _to_review_row
from .keys import make_alias_key, make_legacy_alias_key
from .matcher import match_building
from .normalization import normalize_address_for_matching, normalize_building_input
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
    created: int = 0
    auto_seed_skipped: int = 0


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


def _contains_digit(value: str) -> bool:
    return any(ch.isdigit() for ch in value)


_ACCESS_INFO_NOISE_KEYWORDS = (
    "築年数",
    "階建て",
    "口コミ数",
    "平均賃料",
    "アクセス数",
    "坪賃料",
    "総戸数",
    "管理費",
    "修繕積立金",
)

_FLOOR_LABEL_NOISE_KEYWORDS = (
    "口コミ数",
    "平均賃料",
    "アクセス数",
    "坪賃料",
    "総戸数",
    "築年数",
)


def _is_invalid_access_info(value: str | None) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return True
    if any(keyword in cleaned for keyword in _ACCESS_INFO_NOISE_KEYWORDS):
        return True
    if "線" in cleaned and "駅" not in cleaned:
        return True
    if not any(token in cleaned for token in ("駅", "徒歩", "バス")):
        return True
    if not re.search(r"[一-龥ぁ-んァ-ン]", cleaned):
        return True
    return False


def _is_valid_floor_count_text(value: str | None) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return False
    if cleaned in {"て", "階"}:
        return False
    if "階建て:" in cleaned or "て:" in cleaned:
        return False
    if any(keyword in cleaned for keyword in _FLOOR_LABEL_NOISE_KEYWORDS):
        return False
    if re.fullmatch(r"地上\d+階建", cleaned):
        return True
    if re.fullmatch(r"地上\d+階建\s*地下\d+階", cleaned):
        return True
    if re.fullmatch(r"地下\d+階\s*地上\d+階建", cleaned):
        return True
    return False


def _should_repair_field(existing_value: str | None, new_value: str | None, *, field: str) -> bool:
    existing = _clean_text(existing_value)
    new = _clean_text(new_value)
    if not new:
        return False
    if not existing:
        return True
    if field == "access_info":
        return _is_invalid_access_info(existing) and not _is_invalid_access_info(new)
    if field == "floor_count_text":
        return (not _is_valid_floor_count_text(existing)) and _is_valid_floor_count_text(new)
    return False


def _simplify_for_create(address: str) -> tuple[str, bool]:
    simplified = address
    is_multi_or_range = False
    if "、" in simplified:
        simplified = simplified.split("、", 1)[0]
        is_multi_or_range = True
    if "〜" in simplified:
        simplified = simplified.split("〜", 1)[0]
        is_multi_or_range = True
    return simplified, is_multi_or_range


def _has_high_conflict_for_autoseed(conn, *, normalized_name: str, normalized_address: str) -> bool:
    alias_key = make_alias_key(normalized_name, normalized_address)
    alias_key_legacy = make_legacy_alias_key(normalized_name, normalized_address)
    alias_conflict = conn.execute(
        """
        SELECT 1
        FROM building_key_aliases
        WHERE alias_key IN (?, ?)
        LIMIT 1
        """,
        (alias_key, alias_key_legacy),
    ).fetchone()
    if alias_conflict is not None:
        return True

    canonical_conflict = conn.execute(
        """
        SELECT 1
        FROM buildings
        WHERE norm_name = ? OR norm_address = ?
        LIMIT 1
        """,
        (normalized_name, normalized_address),
    ).fetchone()
    return canonical_conflict is not None




def _recompute_building_age_from_built_year_month(conn, building_id: str) -> None:
    row = conn.execute("SELECT built_year_month FROM buildings WHERE building_id=?", (building_id,)).fetchone()
    if not row:
        return
    recalculated_age = age_years_from_built_year_month(row["built_year_month"])
    if recalculated_age is None:
        return
    conn.execute(
        "UPDATE buildings SET age_years=?, updated_at=CURRENT_TIMESTAMP WHERE building_id=?",
        (recalculated_age, building_id),
    )

def _register_alias(conn, normalized_name: str, normalized_address: str, building_id: str) -> None:
    alias_key = make_alias_key(normalized_name, normalized_address)
    conn.execute(
        """
        INSERT INTO building_key_aliases(alias_key, canonical_key, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(alias_key) DO UPDATE SET
            canonical_key=excluded.canonical_key,
            updated_at=CURRENT_TIMESTAMP
        """,
        (alias_key, building_id),
    )


def ingest_building_facts_csv(
    db_path: str,
    csv_path: str,
    *,
    source: str = "mansion_review_facts",
    merge: str = "fill_only",
    create_missing_safe: bool = False,
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
    created_rows: list[dict[str, str]] = []
    skipped_autoseed_rows: list[dict[str, str]] = []
    seeded_in_run: set[tuple[str, str]] = set()

    alias_rows = conn.execute("SELECT alias_key, canonical_key FROM building_key_aliases").fetchall()
    alias_map = {row["alias_key"]: row["canonical_key"] for row in alias_rows}

    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        got = tuple(reader.fieldnames or ())
        if not set(INPUT_REQUIRED_COLUMNS).issubset(set(got)):
            raise ValueError(f"Unexpected building facts header. got={list(got)} expected_required={list(INPUT_REQUIRED_COLUMNS)}")

        for row in reader:
            report.rows_total += 1
            normalized_source = normalize_source_name(source)
            raw_name = _clean_text(row.get("building_name"))
            raw_address = _clean_text(row.get("address"))
            normalized = normalize_building_input(raw_name, raw_address)
            evidence_id = _clean_text(row.get("evidence_id")) or f"{source}:{report.rows_total}"
            if not normalized.raw_name and not normalized.raw_address:
                reason = "missing_name_and_address"
                report.unresolved += 1
                unmatched_rows.append(
                    _to_review_row(
                        source_kind=source,
                        source_id=evidence_id,
                        normalized_name=normalized.normalized_name,
                        normalized_address=normalized.normalized_address,
                        raw_name=normalized.raw_name,
                        raw_address=normalized.raw_address,
                        reason=reason,
                        candidate_ids=[],
                        candidate_scores=[],
                    )
                )
                insert_unmatched_queue(
                    conn,
                    source=normalized_source,
                    ingest_run_id=None,
                    evidence_id=evidence_id,
                    raw_name=normalized.raw_name,
                    raw_address=normalized.raw_address,
                    normalized_name=normalized.normalized_name,
                    normalized_address=normalized.normalized_address,
                    reason=reason,
                    domain=source_domain(normalized_source),
                )
                continue

            match = match_building(conn, normalized.normalized_name, normalized.normalized_address)
            building_id = match.building_id
            if not building_id and match.reason in {"unmatched", "address_without_digits"}:
                alias_key = make_alias_key(normalized.normalized_name, normalized.normalized_address)
                building_id = alias_map.get(alias_key, "")
                if not building_id:
                    building_id = alias_map.get(make_legacy_alias_key(normalized.normalized_name, normalized.normalized_address), "")

            if building_id:
                alias_key_current = make_alias_key(normalized.normalized_name, normalized.normalized_address)
                if alias_key_current != building_id and alias_map.get(alias_key_current) != building_id:
                    _register_alias(conn, normalized.normalized_name, normalized.normalized_address, building_id)
                    alias_map[alias_key_current] = building_id

            if not building_id and create_missing_safe and source == "mansion_review_list_facts":
                simplified_addr, is_multi_or_range = _simplify_for_create(normalized.normalized_address)
                normalized_address_for_collision = normalize_address_for_matching(simplified_addr)
                auto_seed_skipped_reason = ""
                is_safe_to_create = (
                    bool(normalized.raw_name)
                    and bool(normalized.raw_address)
                    and bool(normalized.normalized_name)
                    and bool(normalized_address_for_collision)
                    and _contains_digit(simplified_addr)
                    and not is_multi_or_range
                    and match.reason == "unmatched"
                )
                if is_safe_to_create and _has_high_conflict_for_autoseed(
                    conn,
                    normalized_name=normalized.normalized_name,
                    normalized_address=normalized_address_for_collision,
                ):
                    is_safe_to_create = False
                    auto_seed_skipped_reason = "collision_with_canonical_or_alias"
                run_seed_key = (normalized.normalized_name, normalized_address_for_collision)
                if is_safe_to_create and run_seed_key in seeded_in_run:
                    is_safe_to_create = False
                    auto_seed_skipped_reason = "duplicate_in_same_run"
                if is_safe_to_create:
                    building_id = make_alias_key(normalized.normalized_name, normalized_address_for_collision)
                    exists = conn.execute("SELECT 1 FROM buildings WHERE building_id=?", (building_id,)).fetchone()
                    if exists is None:
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
                                normalized.canonical_address,
                                normalized.normalized_name,
                                normalized_address_for_collision,
                            ),
                        )
                        report.created += 1
                        seeded_in_run.add(run_seed_key)
                        created_rows.append(
                            {
                                "source": source,
                                "evidence_id": evidence_id,
                                "building_id": building_id,
                                "name": normalized.raw_name,
                                "address": normalized.canonical_address,
                                "norm_name": normalized.normalized_name,
                                "norm_address": normalized_address_for_collision,
                                "source_url": _clean_text(row.get("source_url")) or "",
                            }
                        )
                    _register_alias(conn, normalized.normalized_name, normalized.normalized_address, building_id)
                    alias_map[make_alias_key(normalized.normalized_name, normalized.normalized_address)] = building_id
                else:
                    report.auto_seed_skipped += 1
                    skipped_autoseed_rows.append(
                        {
                            "source": source,
                            "evidence_id": evidence_id,
                            "name": normalized.raw_name,
                            "address": normalized.canonical_address,
                            "norm_name": normalized.normalized_name,
                            "norm_address": normalized_address_for_collision,
                            "match_reason": match.reason,
                            "skip_reason": auto_seed_skipped_reason or "not_high_confidence",
                        }
                    )

            if not building_id:
                resolved_reason = match.reason if match.reason != "unmatched" else "unmatched_canonical_building"
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
                        reason=resolved_reason,
                        candidate_ids=match.candidate_ids,
                        candidate_scores=match.candidate_scores,
                    )
                )
                insert_unmatched_queue(
                    conn,
                    source=normalized_source,
                    ingest_run_id=None,
                    evidence_id=evidence_id,
                    raw_name=normalized.raw_name,
                    raw_address=normalized.raw_address,
                    normalized_name=normalized.normalized_name,
                    normalized_address=normalized.normalized_address,
                    reason=resolved_reason,
                    candidate_building_ids="|".join(match.candidate_ids[:3]),
                    candidate_scores="|".join(str(score) for score in match.candidate_scores[:3]),
                    domain=source_domain(normalized_source),
                )
                continue

            report.matched += 1
            structure = _clean_text(row.get("structure"))
            age_years = _parse_age_years(row.get("age_years"))
            availability_label = _clean_text(row.get("availability_label"))
            built_year_month = _clean_text(row.get("built_year_month"))
            built_age_years = age_years_from_built_year_month(built_year_month)
            if built_age_years is not None:
                age_years = built_age_years
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
            access_info = _clean_text(row.get("access_info"))
            floor_count_text = _clean_text(row.get("floor_count_text"))
            total_units = _parse_int(row.get("total_units"))
            management_style = _clean_text(row.get("management_style"))

            is_mansion_review = source.startswith("mansion_review")
            is_bunjo = property_kind == "bunjo"
            should_repair_access_info = False
            should_repair_floor_count = False
            if merge == "fill_only" and source == "mansion_review_list_facts":
                existing_building = conn.execute(
                    "SELECT access_info, floor_count_text FROM buildings WHERE building_id=?",
                    (building_id,),
                ).fetchone()
                should_repair_access_info = _should_repair_field(
                    existing_building["access_info"] if existing_building else None,
                    access_info,
                    field="access_info",
                )
                should_repair_floor_count = _should_repair_field(
                    existing_building["floor_count_text"] if existing_building else None,
                    floor_count_text,
                    field="floor_count_text",
                )

            if merge == "overwrite" and not is_mansion_review:
                conn.execute(
                    """
                    UPDATE buildings
                    SET canonical_name=COALESCE(NULLIF(canonical_name, ''), ?),
                        canonical_address=COALESCE(NULLIF(canonical_address, ''), ?),
                        structure=COALESCE(NULLIF(?, ''), structure),
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
                        access_info=COALESCE(NULLIF(?, ''), access_info),
                        floor_count_text=COALESCE(NULLIF(?, ''), floor_count_text),
                        total_units=COALESCE(?, total_units),
                        management_style=COALESCE(NULLIF(?, ''), management_style),
                        updated_at=CURRENT_TIMESTAMP
                    WHERE building_id=?
                    """,
                    (
                        normalized.raw_name, normalized.canonical_address,
                        structure, age_years, availability_label, built_year_month, property_kind,
                        sale_price_yen_min, sale_price_yen_max, sale_price_yen_avg,
                        sale_area_sqm_min, sale_area_sqm_max, sale_layout_types_json,
                        sale_listing_count,
                        avg_rent_yen,
                        rental_listing_count,
                        access_info,
                        floor_count_text,
                        total_units,
                        management_style,
                        building_id,
                    ),
                )
            else:
                if is_mansion_review and not is_bunjo:
                    conn.execute(
                        f"""
                        UPDATE buildings
                        SET canonical_name=COALESCE(NULLIF(canonical_name, ''), ?),
                            canonical_address=COALESCE(NULLIF(canonical_address, ''), ?),
                            structure={_fill_only_sql('structure')},
                            age_years=CASE
                                WHEN ? IS NOT NULL THEN ?
                                WHEN age_years IS NULL THEN ?
                                ELSE age_years
                            END,
                            built_year_month={_fill_only_sql('built_year_month')},
                            property_kind={_fill_only_sql('property_kind')},
                            access_info=CASE
                                WHEN access_info IS NULL OR access_info = '' OR ? THEN ?
                                ELSE access_info
                            END,
                            floor_count_text=CASE
                                WHEN floor_count_text IS NULL OR floor_count_text = '' OR ? THEN ?
                                ELSE floor_count_text
                            END,
                            total_units=CASE WHEN total_units IS NULL THEN ? ELSE total_units END,
                            management_style={_fill_only_sql('management_style')},
                            updated_at=CURRENT_TIMESTAMP
                        WHERE building_id=?
                        """,
                        (
                            normalized.raw_name,
                            normalized.canonical_address,
                            structure,
                            built_age_years,
                            built_age_years,
                            age_years,
                            built_year_month,
                            property_kind,
                            should_repair_access_info,
                            access_info,
                            should_repair_floor_count,
                            floor_count_text,
                            total_units,
                            management_style,
                            building_id,
                        ),
                    )
                else:
                    conn.execute(
                        f"""
                        UPDATE buildings
                        SET canonical_name=COALESCE(NULLIF(canonical_name, ''), ?),
                            canonical_address=COALESCE(NULLIF(canonical_address, ''), ?),
                            structure={_fill_only_sql('structure')},
                            age_years=CASE
                                WHEN ? IS NOT NULL THEN ?
                                WHEN age_years IS NULL THEN ?
                                ELSE age_years
                            END,
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
                            access_info=CASE
                                WHEN access_info IS NULL OR access_info = '' OR ? THEN ?
                                ELSE access_info
                            END,
                            floor_count_text=CASE
                                WHEN floor_count_text IS NULL OR floor_count_text = '' OR ? THEN ?
                                ELSE floor_count_text
                            END,
                            total_units=CASE WHEN total_units IS NULL THEN ? ELSE total_units END,
                            management_style={_fill_only_sql('management_style')},
                            updated_at=CURRENT_TIMESTAMP
                        WHERE building_id=?
                        """,
                        (
                            normalized.raw_name, normalized.canonical_address,
                            structure, built_age_years, built_age_years, age_years, availability_label, built_year_month, property_kind,
                            sale_price_yen_min, sale_price_yen_max, sale_price_yen_avg,
                            sale_area_sqm_min, sale_area_sqm_max, sale_layout_types_json,
                            sale_listing_count,
                            avg_rent_yen,
                            rental_listing_count,
                            should_repair_access_info,
                            access_info,
                            should_repair_floor_count,
                            floor_count_text,
                            total_units,
                            management_style,
                            building_id,
                        ),
                    )

            _recompute_building_age_from_built_year_month(conn, building_id)
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

    if created_rows:
        out_created = review_dir / f"new_buildings_{now}.csv"
        with out_created.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "source",
                    "evidence_id",
                    "building_id",
                    "name",
                    "address",
                    "norm_name",
                    "norm_address",
                    "source_url",
                ],
            )
            writer.writeheader()
            writer.writerows(created_rows)
    if skipped_autoseed_rows:
        out_skipped = review_dir / f"auto_seed_skipped_{now}.csv"
        with out_skipped.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["source", "evidence_id", "name", "address", "norm_name", "norm_address", "match_reason", "skip_reason"],
            )
            writer.writeheader()
            writer.writerows(skipped_autoseed_rows)

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
    parser.add_argument("--create-missing-safe", action="store_true")
    args = parser.parse_args()

    report = ingest_building_facts_csv(
        args.db,
        args.csv,
        source=args.source,
        merge=args.merge,
        create_missing_safe=args.create_missing_safe,
    )
    print(
        " ".join(
            [
                f"rows_total={report.rows_total}",
                f"matched={report.matched}",
                f"updated={report.updated}",
                f"unresolved={report.unresolved}",
                f"created={report.created}",
                f"auto_seed_skipped={report.auto_seed_skipped}",
            ]
        )
    )


if __name__ == "__main__":
    main()
