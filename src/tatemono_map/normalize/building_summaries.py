from __future__ import annotations

import argparse
from collections import Counter

from tatemono_map.db.repo import connect, replace_building_summary
from tatemono_map.util.text import normalize_text


def rebuild(db_path: str) -> int:
    conn = connect(db_path)
    rows = conn.execute(
        """
        SELECT building_key, name, address, rent_yen, area_sqm, layout, updated_at
        FROM listings
        ORDER BY id DESC
        """
    ).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row["building_key"], []).append(row)

    conn.execute("DELETE FROM building_summaries")
    count = 0
    for building_key, items in grouped.items():
        rents = [r["rent_yen"] for r in items if r["rent_yen"] is not None]
        areas = [r["area_sqm"] for r in items if r["area_sqm"] is not None]
        layouts = sorted({normalize_text(r["layout"]) for r in items if r["layout"]})
        latest = next((r["updated_at"] for r in items if r["updated_at"]), None)
        replace_building_summary(
            conn,
            {
                "building_key": building_key,
                "name": items[0]["name"],
                "raw_name": items[0]["name"],
                "address": items[0]["address"] or "",
                "rent_yen_min": min(rents) if rents else None,
                "rent_yen_max": max(rents) if rents else None,
                "area_sqm_min": min(areas) if areas else None,
                "area_sqm_max": max(areas) if areas else None,
                "layout_types": layouts,
                "vacancy_count": len(items),
                "last_updated": latest,
            },
        )
        count += 1
    conn.close()
    return count


def summarize_layout_counts(conn, building_key: str) -> list[dict[str, int | str]]:
    rows = conn.execute("SELECT layout FROM listings WHERE building_key=?", (building_key,)).fetchall()
    counter = Counter([(r["layout"] or "不明") for r in rows])
    return [{"layout": k, "count": v} for k, v in sorted(counter.items(), key=lambda x: x[0])]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    args = parser.parse_args()
    n = rebuild(args.db_path)
    print(f"rebuilt building_summaries: {n}")


if __name__ == "__main__":
    main()
