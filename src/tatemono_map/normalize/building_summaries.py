from __future__ import annotations

import argparse
from collections import Counter

from tatemono_map.db.repo import connect, replace_building_summary
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


def refresh_building_availability_labels(conn) -> None:
    conn.execute(
        """
        UPDATE building_summaries AS bs
        SET building_availability_label = CASE
            WHEN EXISTS(
                SELECT 1
                FROM listings AS l
                LEFT JOIN building_key_aliases AS bka ON bka.alias_key = l.building_key
                WHERE COALESCE(bka.canonical_key, l.building_key) = bs.building_key
                  AND (COALESCE(l.availability_raw, '') LIKE '%即入%' OR COALESCE(l.availability_flag_immediate, 0)=1)
            ) THEN '即入'
            WHEN EXISTS(
                SELECT 1
                FROM listings AS l
                LEFT JOIN building_key_aliases AS bka ON bka.alias_key = l.building_key
                WHERE COALESCE(bka.canonical_key, l.building_key) = bs.building_key
                  AND COALESCE(l.availability_raw, '') LIKE '%空室%'
            ) THEN '空室'
            WHEN EXISTS(
                SELECT 1
                FROM listings AS l
                LEFT JOIN building_key_aliases AS bka ON bka.alias_key = l.building_key
                WHERE COALESCE(bka.canonical_key, l.building_key) = bs.building_key
                  AND COALESCE(l.availability_raw, '') LIKE '%退去予定%'
            ) THEN '退去予定'
            ELSE ''
        END
        """
    )


def rebuild(db_path: str) -> int:
    conn = connect(db_path)
    conn.execute("DELETE FROM building_summaries")

    building_rows = conn.execute(
        """
        SELECT building_id, canonical_name, canonical_address
        FROM buildings
        """
    ).fetchall()

    alias_rows = conn.execute("SELECT alias_key, canonical_key FROM building_key_aliases").fetchall()
    alias_map = {row["alias_key"]: row["canonical_key"] for row in alias_rows}

    rows = conn.execute(
        """
        SELECT building_key, name, address, rent_yen, area_sqm, layout, move_in_date, updated_at,
               age_years, structure, availability_raw, built_raw, structure_raw,
               built_year_month, built_age_years, availability_flag_immediate
        FROM listings
        ORDER BY id DESC
        """
    ).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        if not row["building_key"]:
            continue
        canonical_key = alias_map.get(row["building_key"], row["building_key"])
        grouped.setdefault(canonical_key, []).append(row)

    canonical_by_id = {row["building_id"]: row for row in building_rows}
    target_keys = set(canonical_by_id.keys()) | set(grouped.keys())

    for building_key in sorted(target_keys):
        items = grouped.get(building_key, [])
        building = canonical_by_id.get(building_key)
        rents = [r["rent_yen"] for r in items if r["rent_yen"] is not None]
        areas = [r["area_sqm"] for r in items if r["area_sqm"] is not None]
        layouts = sorted({normalize_text(r["layout"]) for r in items if r["layout"]})
        move_in_dates = sorted({normalize_text(r["move_in_date"]) for r in items if r["move_in_date"]})
        age_values = [int(r["age_years"]) for r in items if r["age_years"] is not None]
        structure_values = [r["structure"] for r in items if r["structure"]]
        built_year_month_values = [r["built_year_month"] for r in items if r["built_year_month"]]
        built_age_values = [int(r["built_age_years"]) for r in items if r["built_age_years"] is not None]
        building_structure_values = [r["structure_raw"] for r in items if r["structure_raw"]]
        latest = max((r["updated_at"] for r in items if r["updated_at"]), default=None)
        summary_name = building["canonical_name"] if building else (items[0]["name"] if items else None)
        summary_address = building["canonical_address"] if building else (items[0]["address"] if items else None)
        summary_raw_name = summary_name

        replace_building_summary(
            conn,
            {
                "building_key": building_key,
                "name": summary_name,
                "raw_name": summary_raw_name,
                "address": summary_address,
                "rent_yen_min": min(rents) if rents else None,
                "rent_yen_max": max(rents) if rents else None,
                "area_sqm_min": min(areas) if areas else None,
                "area_sqm_max": max(areas) if areas else None,
                "layout_types": layouts,
                "move_in_dates": move_in_dates,
                "age_years": _pick_age_years(age_values),
                "structure": _pick_structure(structure_values),
                "building_built_year_month": _pick_built_year_month(built_year_month_values),
                "building_built_age_years": _pick_age_years(built_age_values),
                "building_structure": _pick_structure(building_structure_values) or _pick_structure(structure_values),
                "building_availability_label": "",
                "vacancy_count": len(items),
                "last_updated": latest,
            },
        )

    refresh_building_availability_labels(conn)

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
