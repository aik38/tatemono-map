from __future__ import annotations

import argparse

from tatemono_map.db.repo import connect, replace_building_summary
from tatemono_map.util.text import normalize_text

def rebuild(db_path: str) -> int:
    conn = connect(db_path)
    conn.execute("DELETE FROM building_summaries")

    building_rows = conn.execute(
        """
        SELECT building_id, canonical_name, canonical_address
        FROM buildings
        """
    ).fetchall()

    rows = conn.execute(
        """
        SELECT building_key, name, address, rent_yen, area_sqm, layout, move_in_date, updated_at
        FROM listings
        ORDER BY id DESC
        """
    ).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        if not row["building_key"]:
            continue
        grouped.setdefault(row["building_key"], []).append(row)

    canonical_by_id = {row["building_id"]: row for row in building_rows}
    target_keys = set(canonical_by_id.keys()) | set(grouped.keys())

    for building_key in sorted(target_keys):
        items = grouped.get(building_key, [])
        building = canonical_by_id.get(building_key)
        rents = [r["rent_yen"] for r in items if r["rent_yen"] is not None]
        areas = [r["area_sqm"] for r in items if r["area_sqm"] is not None]
        layouts = sorted({normalize_text(r["layout"]) for r in items if r["layout"]})
        move_in_dates = sorted({normalize_text(r["move_in_date"]) for r in items if r["move_in_date"]})
        latest = max((r["updated_at"] for r in items if r["updated_at"]), default=None)
        summary_name = (building["canonical_name"] if building else None) or (items[0]["name"] if items else None)
        summary_address = (building["canonical_address"] if building else None) or (items[0]["address"] if items else None)
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
                "vacancy_count": len(items),
                "last_updated": latest,
            },
        )

    total = conn.execute("SELECT COUNT(*) AS c FROM building_summaries").fetchone()["c"]
    print(
        "seeded_buildings={} listings={} distinct_stable_buildings_in_listings={} building_summaries_total={}".format(
            len(building_rows),
            len(rows),
            len(grouped),
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
