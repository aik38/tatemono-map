from __future__ import annotations

import argparse
import json
import os
import re
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


def _is_valid_access_info(value: str | None) -> bool:
    cleaned = normalize_text(value)
    if not cleaned:
        return False
    if "線" in cleaned and "駅" not in cleaned:
        return False
    return any(token in cleaned for token in ("駅", "徒歩", "バス"))


def _is_valid_floor_count_text(value: str | None) -> bool:
    cleaned = normalize_text(value)
    if not cleaned:
        return False
    if "て:" in cleaned or "階建て:" in cleaned:
        return False
    return re.fullmatch(r"(地上\d+階建|地上\d+階建\s*地下\d+階|地下\d+階\s*地上\d+階建)", cleaned) is not None


def _pick_latest_valid_value(rows: list[dict], field: str, *, validator=None):
    for row in sorted(rows, key=lambda r: (normalize_text(r.get("updated_at")) or "", str(r.get("building_id") or "")), reverse=True):
        value = row.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            value = normalize_text(value)
            if not value:
                continue
        if validator and not validator(value):
            continue
        return value
    return None


def _pick_latest_nonempty_listing_field(rows: list, field: str):
    for row in sorted(rows, key=lambda r: (normalize_text(r["updated_at"]) or ""), reverse=True):
        value = row[field]
        if value is None:
            continue
        if isinstance(value, str):
            value = normalize_text(value)
            if not value:
                continue
        return value
    return None


_SALE_LAYOUT_RE = re.compile(r"\d+\s*(?:SLDK|LDK|SDK|DK|K|R|ワンルーム)", re.IGNORECASE)


def _natural_sort_key(value: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value))


def _distinct_natural(values: list[str]) -> list[str]:
    deduped = {normalize_text(v) for v in values if normalize_text(v)}
    return sorted(deduped, key=_natural_sort_key)


def _distinct_in_seen_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = normalize_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _normalize_sale_row_fields(row: dict) -> dict:
    normalized = dict(row)
    floor_text = normalize_text(normalized.get("floor_text"))
    direction_text = normalize_text(normalized.get("direction_text"))
    layout = normalize_text(normalized.get("layout"))
    area_sqm = normalized.get("area_sqm")
    sqm_unit_price_yen = normalized.get("sqm_unit_price_yen")

    if area_sqm is None and floor_text and re.search(r"(?:㎡|m2|m²)", floor_text, flags=re.IGNORECASE):
        area_match = re.search(r"(\d+(?:\.\d+)?)", floor_text.replace(",", ""))
        if area_match:
            normalized["area_sqm"] = float(area_match.group(1))
            normalized["floor_text"] = None
            floor_text = None

    if layout and sqm_unit_price_yen is None and re.search(r"万円", layout):
        match = re.search(r"(\d+(?:\.\d+)?)", layout.replace(",", ""))
        if match:
            normalized["sqm_unit_price_yen"] = int(float(match.group(1)) * 10000)
            normalized["layout"] = direction_text if direction_text and _SALE_LAYOUT_RE.search(direction_text) else None
            if direction_text and _SALE_LAYOUT_RE.search(direction_text):
                normalized["direction_text"] = None

    normalized_direction = normalize_text(normalized.get("direction_text"))
    if normalized_direction and _SALE_LAYOUT_RE.search(normalized_direction):
        normalized["direction_text"] = None

    return normalized


def _is_effective_sale_item(row: dict) -> bool:
    return any(
        row.get(field) is not None and row.get(field) != ""
        for field in (
            "price_yen",
            "area_sqm",
            "layout",
            "floor_text",
            "direction_text",
            "management_fee_yen",
            "repair_fund_yen",
            "sqm_unit_price_yen",
        )
    )


def _filter_latest_valid_sale_items(sale_items: list[dict]) -> list[dict]:
    normalized = [_normalize_sale_row_fields(dict(r)) for r in sale_items]
    effective = [row for row in normalized if _is_effective_sale_item(row)]
    if not effective:
        return []

    dated = [row for row in effective if normalize_text(row.get("updated_at"))]
    if not dated:
        return effective

    normalized_timestamps = [normalize_text(row.get("updated_at")) or "" for row in dated]
    distinct_timestamps = sorted(set(normalized_timestamps))
    has_time_component = all(" " in ts for ts in distinct_timestamps if ts)
    if not (has_time_component and len(distinct_timestamps) > 1):
        return effective

    latest_ts = distinct_timestamps[-1]
    latest_rows = [row for row in dated if (normalize_text(row.get("updated_at")) or "") == latest_ts]
    return latest_rows or effective


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
        SELECT building_key, price_yen, management_fee_yen, repair_fund_yen, tsubo_unit_price_yen AS sqm_unit_price_yen, area_sqm, layout, floor_text, direction_text, updated_at, source
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
    trace_target_names = {
        "エクレール東新町",
        "エメラルドハイツ大里3",
        "パサージュ門司",
        "門司港レトロハイマート",
    }
    trace_records: list[dict] = []
    def _write_sale_trace() -> None:
        trace_out = os.environ.get("TATEMONO_TRACE_OUT")
        trace_path = os.path.abspath(trace_out) if trace_out else "tmp/building_summaries_sale_trace.json"
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace_records, f, ensure_ascii=False, indent=2)

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
               avg_rent_yen, rental_listing_count, management_style, floor_count_text, total_units,
               access_info, updated_at
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
        SELECT building_key, price_yen, management_fee_yen, repair_fund_yen, tsubo_unit_price_yen AS sqm_unit_price_yen, area_sqm, layout, floor_text, direction_text, updated_at, source
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

    building_dicts = [dict(row) for row in building_rows]
    canonical_by_id = {row["building_id"]: row for row in building_dicts}
    grouped_buildings: dict[str, list[dict]] = {key: [row] for key, row in canonical_by_id.items()}
    for alias_key, canonical_key in alias_map.items():
        alias_row = canonical_by_id.get(alias_key)
        if not alias_row:
            continue
        grouped_buildings.setdefault(canonical_key, [])
        if all(existing["building_id"] != alias_key for existing in grouped_buildings[canonical_key]):
            grouped_buildings[canonical_key].append(alias_row)
    merged_canonical_by_id: dict[str, dict] = {}
    for building_id, base in canonical_by_id.items():
        merged = dict(base)
        candidates = grouped_buildings.get(building_id, [base])
        merged["access_info"] = _pick_latest_valid_value(candidates, "access_info", validator=_is_valid_access_info) or merged.get("access_info")
        merged["floor_count_text"] = _pick_latest_valid_value(candidates, "floor_count_text", validator=_is_valid_floor_count_text) or merged.get("floor_count_text")
        merged["total_units"] = _pick_latest_valid_value(candidates, "total_units", validator=lambda v: isinstance(v, int) and v > 0) or merged.get("total_units")
        merged["built_year_month"] = _pick_latest_valid_value(candidates, "built_year_month") or merged.get("built_year_month")
        merged["age_years"] = _pick_latest_valid_value(candidates, "age_years", validator=lambda v: isinstance(v, int) and v >= 0) or merged.get("age_years")
        merged_canonical_by_id[building_id] = merged

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
        building = merged_canonical_by_id.get(building_key)
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

        normalized_sale_items = _filter_latest_valid_sale_items(sale_items)
        normalized_sale_rows_all = [_normalize_sale_row_fields(dict(r)) for r in sale_items]
        filtered_sale_items = normalized_sale_items
        sale_prices = [int(r["price_yen"]) for r in normalized_sale_items if r["price_yen"] is not None]
        sale_areas = [float(r["area_sqm"]) for r in normalized_sale_items if r["area_sqm"] is not None]
        sale_layouts = _distinct_natural([str(r.get("layout") or "") for r in normalized_sale_items])
        sale_mgmt_fees = [int(r["management_fee_yen"]) for r in normalized_sale_items if r["management_fee_yen"] is not None]
        sale_repair_funds = [int(r["repair_fund_yen"]) for r in normalized_sale_items if r["repair_fund_yen"] is not None]
        sale_sqm_unit_prices = [int(r["sqm_unit_price_yen"]) for r in normalized_sale_items if r["sqm_unit_price_yen"] is not None]
        sale_floors = _distinct_in_seen_order([str(r.get("floor_text") or "") for r in normalized_sale_items])
        sale_directions = _distinct_natural([str(r.get("direction_text") or "") for r in normalized_sale_items])
        sale_latest = max((r["updated_at"] for r in normalized_sale_items if r["updated_at"]), default=None)

        sale_price_min = min(sale_prices) if sale_prices else (building["sale_price_yen_min"] if building else None)
        sale_price_max = max(sale_prices) if sale_prices else (building["sale_price_yen_max"] if building else None)
        sale_price_avg = (sum(sale_prices) // len(sale_prices)) if sale_prices else (building["sale_price_yen_avg"] if building else None)
        sale_area_min = min(sale_areas) if sale_areas else (building["sale_area_sqm_min"] if building else None)
        sale_area_max = max(sale_areas) if sale_areas else (building["sale_area_sqm_max"] if building else None)
        sale_layout_types_json = (
            json.dumps(sale_layouts, ensure_ascii=False)
            if sale_layouts
            else (building["sale_layout_types_json"] if building else None)
        )
        sale_listing_count = (
            len(normalized_sale_items)
            if normalized_sale_items
            else (building["sale_listing_count"] if building else None)
        )
        if (
            not sale_prices
            and (sale_listing_count or 0) > 1
            and sale_price_min is not None
            and sale_price_max is not None
            and sale_price_min == sale_price_max
        ):
            sale_price_min = None
            sale_price_max = None
            sale_price_avg = None

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
        sale_upsert_payload = {
            "sale_listing_count": sale_listing_count or 0,
            "price_yen_min": sale_price_min,
            "price_yen_max": sale_price_max,
            "price_yen_avg": sale_price_avg,
            "area_sqm_min": sale_area_min,
            "area_sqm_max": sale_area_max,
            "floor_summary": ", ".join(sale_floors) if sale_floors else None,
            "direction_summary": ", ".join(sale_directions) if sale_directions else None,
            "updated_at": max(filter(None, [latest, sale_latest]), default=None),
        }
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
                    sale_upsert_payload["sale_listing_count"],
                    sale_price_min,
                    sale_price_max,
                    sale_area_min,
                    sale_area_max,
                    sale_layout_types_json or "[]",
                    sale_upsert_payload["floor_summary"],
                    sale_upsert_payload["direction_summary"],
                    min(sale_sqm_unit_prices) if sale_sqm_unit_prices else None,
                    max(sale_sqm_unit_prices) if sale_sqm_unit_prices else None,
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
                    sale_upsert_payload["updated_at"],
                ),
            )
        if summary_name in trace_target_names:
            post_upsert_row = conn.execute(
                """
                SELECT *
                FROM building_sale_summaries
                WHERE building_key = ?
                """,
                (building_key,),
            ).fetchone()
            trace_records.append(
                {
                    "summary_name": summary_name,
                    "building_key": building_key,
                    "sale_rows_raw_count": len(sale_items),
                    "sale_rows_updated_at_list": [
                        normalize_text(dict(row).get("updated_at"))
                        for row in sale_items
                        if normalize_text(dict(row).get("updated_at"))
                    ],
                    "normalized_sale_items_count": len(normalized_sale_rows_all),
                    "filtered_sale_items_count": len(filtered_sale_items),
                    "filtered_rows": [
                        {
                            "price_yen": row.get("price_yen"),
                            "area_sqm": row.get("area_sqm"),
                            "layout": row.get("layout"),
                            "floor_text": row.get("floor_text"),
                            "direction_text": row.get("direction_text"),
                            "updated_at": row.get("updated_at"),
                        }
                        for row in filtered_sale_items
                    ],
                    "upsert_payload": sale_upsert_payload,
                    "post_upsert_row": dict(post_upsert_row) if post_upsert_row else None,
                }
            )
            _write_sale_trace()

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
    if trace_records:
        _write_sale_trace()
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
