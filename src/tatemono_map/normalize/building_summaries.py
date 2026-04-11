from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date

from tatemono_map.db.repo import connect, replace_building_summary
from tatemono_map.util.building_age import age_years_from_built_year_month
from tatemono_map.util.text import normalize_text


def _median_int(values: list[int]) -> int:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return int((ordered[mid - 1] + ordered[mid]) / 2)


# TODO(source-priority): when additional providers are ingested, apply source priority before mode aggregation.
def _pick_age_years(values: list[int]) -> int | None:
    if not values:
        return None
    counts = Counter(values)
    max_count = max(counts.values())
    modes = sorted(value for value, count in counts.items() if count == max_count)
    if len(modes) == 1:
        return modes[0]
    return _median_int(values)


def _pick_structure(values: list[str]) -> str | None:
    normalized_values = [normalize_text(v) for v in values if normalize_text(v)]
    if not normalized_values:
        return None
    counts = Counter(normalized_values)
    max_count = max(counts.values())
    modes = sorted(value for value, count in counts.items() if count == max_count)
    return modes[0]


def _pick_built_year_month(values: list[str]) -> str | None:
    normalized_values = [normalize_text(v) for v in values if normalize_text(v)]
    if not normalized_values:
        return None
    counts = Counter(normalized_values)
    max_count = max(counts.values())
    modes = sorted(value for value, count in counts.items() if count == max_count)
    return modes[0]


def _nearest_availability_date(items: list) -> str | None:
    dates: list[date] = []
    for row in items:
        raw_date = normalize_text(row["availability_date"])
        if not raw_date:
            continue
        try:
            dates.append(date.fromisoformat(raw_date))
        except ValueError:
            continue
    if not dates:
        return None
    return min(dates).isoformat()


def _select_availability_label(move_in_dates: list[str], items: list) -> str:
    if any((row["availability_flag_immediate"] or 0) == 1 or "即入" in (row["availability_raw"] or "") for row in items):
        return "入居"

    nearest = _nearest_availability_date(items)
    if nearest:
        return nearest
    if move_in_dates:
        return move_in_dates[0]

    planned = [normalize_text(row["availability_raw"]) for row in items if normalize_text(row["availability_raw"])]
    for raw in planned:
        if "退去予定" in raw:
            return raw

    for raw in planned:
        if raw not in {"-", "--", "- -", "なし"}:
            return raw
    return ""


def refresh_building_availability_labels(conn) -> None:
    # Labels are computed in rebuild() before persisting summaries.
    return None


def _load_priority_rank(conn, domain: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT source, priority_rank
        FROM source_priority
        WHERE domain = ? AND enabled = 1
        ORDER BY priority_rank ASC
        """,
        (domain,),
    ).fetchall()
    sale_rows = conn.execute(
        """
        SELECT building_key, price_yen, management_fee_yen, repair_fund_yen, tsubo_unit_price_yen, area_sqm, layout, floor_text, direction_text, updated_at, source
        FROM sale_listings
        WHERE (
            ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots)
            OR (
                ingest_run_id IS NULL
                AND NOT EXISTS (SELECT 1 FROM current_ingest_snapshots)
            )
        )
        ORDER BY id DESC
        """
    ).fetchall()
    return {str(row["source"]): int(row["priority_rank"]) for row in rows}


def rebuild(db_path: str) -> int:
    conn = connect(db_path)
    conn.execute("DELETE FROM building_summaries")
    conn.execute("DELETE FROM building_rental_summaries")
    conn.execute("DELETE FROM building_sale_summaries")
    rental_priority = _load_priority_rank(conn, "rental")

    building_rows = conn.execute(
        """
        SELECT building_id, canonical_name, canonical_address,
               structure, age_years, built_year, built_year_month, availability_raw, availability_label,
               property_kind, sale_price_yen_min, sale_price_yen_max, sale_price_yen_avg,
               sale_area_sqm_min, sale_area_sqm_max, sale_layout_types_json, sale_listing_count,
               avg_rent_yen, rental_listing_count, management_style, floor_count_text, total_units
        FROM buildings
        """
    ).fetchall()

    alias_rows = conn.execute("SELECT alias_key, canonical_key FROM building_key_aliases").fetchall()
    alias_map = {row["alias_key"]: row["canonical_key"] for row in alias_rows}

    rows = conn.execute(
        """
        SELECT building_key, name, address, rent_yen, maint_yen, area_sqm, layout, move_in_date, updated_at,
               age_years, structure, availability_raw, built_raw, structure_raw,
               built_year_month, built_age_years, availability_date, availability_flag_immediate, source_kind
        FROM listings
        WHERE (
            ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots)
            OR (
                ingest_run_id IS NULL
                AND NOT EXISTS (SELECT 1 FROM current_ingest_snapshots)
            )
        )
        ORDER BY id DESC
        """
    ).fetchall()
    sale_rows = conn.execute(
        """
        SELECT building_key, price_yen, management_fee_yen, repair_fund_yen, tsubo_unit_price_yen, area_sqm, layout, floor_text, direction_text, updated_at, source
        FROM sale_listings
        WHERE (
            ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots)
            OR (
                ingest_run_id IS NULL
                AND NOT EXISTS (SELECT 1 FROM current_ingest_snapshots)
            )
        )
        ORDER BY id DESC
        """
    ).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        if not row["building_key"]:
            continue
        canonical_key = alias_map.get(row["building_key"], row["building_key"])
        grouped.setdefault(canonical_key, []).append(row)
    grouped_sale: dict[str, list] = {}
    for row in sale_rows:
        if not row["building_key"]:
            continue
        canonical_key = alias_map.get(row["building_key"], row["building_key"])
        grouped_sale.setdefault(canonical_key, []).append(row)

    canonical_by_id = {row["building_id"]: row for row in building_rows}
    target_keys = set(canonical_by_id.keys()) | set(grouped.keys()) | set(grouped_sale.keys())

    for building_key in sorted(target_keys):
        items = grouped.get(building_key, [])
        sale_items = grouped_sale.get(building_key, [])
        if items and rental_priority:
            ranked_items = [row for row in items if rental_priority.get(str(row["source_kind"])) is not None]
            available_ranks = [rental_priority.get(str(row["source_kind"])) for row in ranked_items]
            if available_ranks and len(ranked_items) == len(items):
                best_rank = min(available_ranks)
                items = [row for row in items if rental_priority.get(str(row["source_kind"])) == best_rank]
        building = canonical_by_id.get(building_key)
        rents = [r["rent_yen"] for r in items if r["rent_yen"] is not None]
        maints = [r["maint_yen"] for r in items if r["maint_yen"] is not None]
        areas = [r["area_sqm"] for r in items if r["area_sqm"] is not None]
        layouts = sorted({normalize_text(r["layout"]) for r in items if r["layout"]})
        move_in_dates = sorted({normalize_text(r["move_in_date"]) for r in items if r["move_in_date"]})
        age_values = [int(r["age_years"]) for r in items if r["age_years"] is not None]
        structure_values = [
            r["structure"]
            for r in items
            if r["structure"] and str(r["source_kind"] or "") != "mansion_review_chintai"
        ]
        built_year_month_values = [r["built_year_month"] for r in items if r["built_year_month"]]
        built_age_values = [int(r["built_age_years"]) for r in items if r["built_age_years"] is not None]
        building_structure_values = [
            r["structure_raw"]
            for r in items
            if r["structure_raw"] and str(r["source_kind"] or "") != "mansion_review_chintai"
        ]
        latest = max((r["updated_at"] for r in items if r["updated_at"]), default=None)
        summary_name = building["canonical_name"] if building else (items[0]["name"] if items else None)
        summary_address = building["canonical_address"] if building else (items[0]["address"] if items else None)
        summary_raw_name = summary_name

        listing_age = _pick_age_years(age_values)
        listing_structure = _pick_structure(structure_values)
        listing_built_year_month = _pick_built_year_month(built_year_month_values)
        listing_built_age = _pick_age_years(built_age_values)
        listing_building_structure = _pick_structure(building_structure_values) or listing_structure

        fallback_age = building["age_years"] if building else None
        fallback_structure = normalize_text(building["structure"]) if building else None
        fallback_built_year_month = (
            normalize_text(building["built_year_month"]) if building and building["built_year_month"] else None
        ) or (f"{building['built_year']}-01" if building and building["built_year"] else None)
        listing_derived_age_from_built = age_years_from_built_year_month(listing_built_year_month)
        derived_age_from_built = age_years_from_built_year_month(fallback_built_year_month)
        resolved_built_age_years = (
            listing_derived_age_from_built
            if listing_derived_age_from_built is not None
            else (listing_built_age if listing_built_age is not None else (derived_age_from_built if derived_age_from_built is not None else fallback_age))
        )
        fallback_availability_label = (normalize_text(building["availability_label"]) if building else "") or None
        fallback_property_kind = normalize_text(building["property_kind"]) if building and building["property_kind"] else ""

        sale_prices = [int(r["price_yen"]) for r in sale_items if r["price_yen"] is not None]
        sale_areas = [float(r["area_sqm"]) for r in sale_items if r["area_sqm"] is not None]
        sale_layouts = sorted({normalize_text(r["layout"]) for r in sale_items if r["layout"]})
        sale_mgmt_fees = [int(r["management_fee_yen"]) for r in sale_items if r["management_fee_yen"] is not None]
        sale_repair_funds = [int(r["repair_fund_yen"]) for r in sale_items if r["repair_fund_yen"] is not None]
        sale_tsubo_unit_prices = [int(r["tsubo_unit_price_yen"]) for r in sale_items if r["tsubo_unit_price_yen"] is not None]
        sale_floors = sorted({normalize_text(r["floor_text"]) for r in sale_items if normalize_text(r["floor_text"])})
        sale_directions = sorted({normalize_text(r["direction_text"]) for r in sale_items if normalize_text(r["direction_text"])})
        sale_latest = max((r["updated_at"] for r in sale_items if r["updated_at"]), default=None)

        sale_price_min = min(sale_prices) if sale_prices else (building["sale_price_yen_min"] if building else None)
        sale_price_max = max(sale_prices) if sale_prices else (building["sale_price_yen_max"] if building else None)
        sale_price_avg = (sum(sale_prices) // len(sale_prices)) if sale_prices else (building["sale_price_yen_avg"] if building else None)
        sale_area_min = min(sale_areas) if sale_areas else (building["sale_area_sqm_min"] if building else None)
        sale_area_max = max(sale_areas) if sale_areas else (building["sale_area_sqm_max"] if building else None)
        sale_layout_types_json = json.dumps(sale_layouts, ensure_ascii=False) if sale_layouts else (building["sale_layout_types_json"] if building else None)
        sale_listing_count = len(sale_items) if sale_items else (building["sale_listing_count"] if building else None)

        availability_label = (_select_availability_label(move_in_dates, items) if items else None) or fallback_availability_label
        vacancy_count = len(items)
        has_rental = vacancy_count > 0
        has_sale_payload = any(
            value is not None and value != ""
            for value in (
                sale_price_min,
                sale_price_max,
                sale_price_avg,
                sale_area_min,
                sale_area_max,
                sale_layout_types_json,
            )
        )
        has_sale = bool((sale_listing_count or 0) > 0 or has_sale_payload or fallback_property_kind == "bunjo")
        if fallback_property_kind == "bunjo" or vacancy_count <= 0:
            availability_label = None

        replace_building_summary(
            conn,
            {
                "building_key": building_key,
                "name": summary_name,
                "raw_name": summary_raw_name,
                "address": summary_address,
                "property_kind": fallback_property_kind,
                "rent_yen_min": min(rents) if rents else None,
                "rent_yen_max": max(rents) if rents else None,
                "sale_price_yen_min": sale_price_min,
                "sale_price_yen_max": sale_price_max,
                "sale_price_yen_avg": sale_price_avg,
                "area_sqm_min": min(areas) if areas else None,
                "area_sqm_max": max(areas) if areas else None,
                "sale_area_sqm_min": sale_area_min,
                "sale_area_sqm_max": sale_area_max,
                "layout_types": layouts,
                "sale_layout_types_json": sale_layout_types_json,
                "move_in_dates": move_in_dates,
                "age_years": resolved_built_age_years if resolved_built_age_years is not None else listing_age,
                "structure": listing_structure or fallback_structure,
                "building_built_year_month": listing_built_year_month or fallback_built_year_month,
                "building_built_age_years": resolved_built_age_years,
                "building_structure": listing_building_structure or fallback_structure,
                "building_availability_label": availability_label,
                "has_rental": has_rental,
                "has_sale": has_sale,
                "vacancy_count": vacancy_count,
                "sale_listing_count": sale_listing_count,
                "last_updated": max(filter(None, [latest, sale_latest]), default=None),
            },
        )
        if has_rental:
            conn.execute(
                """
                INSERT INTO building_rental_summaries(
                    building_key, vacancy_count, rent_yen_min, rent_yen_max, maint_yen_min, maint_yen_max,
                    layout_types_json, area_sqm_min, area_sqm_max, move_in_summary, built_year_month,
                    built_age_years, structure, fetched_date, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, DATE('now'), ?)
                ON CONFLICT(building_key) DO UPDATE SET
                    vacancy_count=excluded.vacancy_count,
                    rent_yen_min=excluded.rent_yen_min,
                    rent_yen_max=excluded.rent_yen_max,
                    maint_yen_min=excluded.maint_yen_min,
                    maint_yen_max=excluded.maint_yen_max,
                    layout_types_json=excluded.layout_types_json,
                    area_sqm_min=excluded.area_sqm_min,
                    area_sqm_max=excluded.area_sqm_max,
                    move_in_summary=excluded.move_in_summary,
                    built_year_month=excluded.built_year_month,
                    built_age_years=excluded.built_age_years,
                    structure=excluded.structure,
                    fetched_date=excluded.fetched_date,
                    updated_at=excluded.updated_at
                """,
                (
                    building_key,
                    vacancy_count,
                    min(rents) if rents else None,
                    max(rents) if rents else None,
                    min(maints) if maints else None,
                    max(maints) if maints else None,
                    json.dumps(layouts, ensure_ascii=False),
                    min(areas) if areas else None,
                    max(areas) if areas else None,
                    availability_label,
                    listing_built_year_month or fallback_built_year_month,
                    resolved_built_age_years,
                    listing_building_structure or fallback_structure,
                    latest,
                ),
            )
        if has_sale:
            conn.execute(
                """
                INSERT INTO building_sale_summaries(
                    building_key, sale_listing_count, price_yen_min, price_yen_max, area_sqm_min, area_sqm_max,
                    layout_types_json, floor_summary, direction_summary, tsubo_unit_price_yen_min, tsubo_unit_price_yen_max, management_fee_yen_min, management_fee_yen_max,
                    repair_fund_yen_min, repair_fund_yen_max, management_style, built_year_month, built_age_years,
                    structure, floor_count_text, total_units, fetched_date, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, DATE('now'), ?)
                ON CONFLICT(building_key) DO UPDATE SET
                    sale_listing_count=excluded.sale_listing_count,
                    price_yen_min=excluded.price_yen_min,
                    price_yen_max=excluded.price_yen_max,
                    area_sqm_min=excluded.area_sqm_min,
                    area_sqm_max=excluded.area_sqm_max,
                    layout_types_json=excluded.layout_types_json,
                    floor_summary=excluded.floor_summary,
                    direction_summary=excluded.direction_summary,
                    tsubo_unit_price_yen_min=excluded.tsubo_unit_price_yen_min,
                    tsubo_unit_price_yen_max=excluded.tsubo_unit_price_yen_max,
                    management_fee_yen_min=excluded.management_fee_yen_min,
                    management_fee_yen_max=excluded.management_fee_yen_max,
                    repair_fund_yen_min=excluded.repair_fund_yen_min,
                    repair_fund_yen_max=excluded.repair_fund_yen_max,
                    management_style=excluded.management_style,
                    built_year_month=excluded.built_year_month,
                    built_age_years=excluded.built_age_years,
                    structure=excluded.structure,
                    floor_count_text=excluded.floor_count_text,
                    total_units=excluded.total_units,
                    fetched_date=excluded.fetched_date,
                    updated_at=excluded.updated_at
                """,
                (
                    building_key,
                    sale_listing_count or 0,
                    sale_price_min,
                    sale_price_max,
                    sale_area_min,
                    sale_area_max,
                    sale_layout_types_json or "[]",
                    ", ".join(sale_floors) if sale_floors else None,
                    ", ".join(sale_directions) if sale_directions else None,
                    min(sale_tsubo_unit_prices) if sale_tsubo_unit_prices else None,
                    max(sale_tsubo_unit_prices) if sale_tsubo_unit_prices else None,
                    min(sale_mgmt_fees) if sale_mgmt_fees else None,
                    max(sale_mgmt_fees) if sale_mgmt_fees else None,
                    min(sale_repair_funds) if sale_repair_funds else None,
                    max(sale_repair_funds) if sale_repair_funds else None,
                    (building["management_style"] if building else None),
                    listing_built_year_month or fallback_built_year_month,
                    resolved_built_age_years,
                    listing_building_structure or fallback_structure,
                    (building["floor_count_text"] if building else None),
                    (building["total_units"] if building else None),
                    max(filter(None, [latest, sale_latest]), default=None),
                ),
            )

    total = conn.execute("SELECT COUNT(*) AS c FROM building_summaries").fetchone()["c"]
    print(
        "seeded_buildings={} listings={} distinct_canonical_buildings_in_listings={} aliases={} building_summaries_total={}".format(
            len(building_rows),
            len(rows),
            len(grouped),
            len(alias_rows),
            total,
        )
    )

    conn.commit()
    conn.close()
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    args = parser.parse_args()
    n = rebuild(args.db_path)
    print(f"rebuilt building_summaries: {n}")


if __name__ == "__main__":
    main()
