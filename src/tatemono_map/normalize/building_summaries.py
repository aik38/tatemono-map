from __future__ import annotations

import argparse
import csv
from pathlib import Path

from tatemono_map.db.repo import connect, replace_building_summary
from tatemono_map.util.text import normalize_text


def _load_alias_map(alias_csv: str) -> dict[str, str]:
    if not alias_csv:
        return {}
    path = Path(alias_csv)
    if not path.exists():
        raise FileNotFoundError(f"alias csv not found: {alias_csv}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV header missing: {alias_csv}")
        return {
            (row.get("old_building_key") or "").strip(): (row.get("new_building_key") or "").strip()
            for row in reader
            if (row.get("old_building_key") or "").strip() and (row.get("new_building_key") or "").strip()
        }


def rebuild(db_path: str, alias_csv: str = "") -> int:
    conn = connect(db_path)
    alias_map = _load_alias_map(alias_csv)

    conn.execute(
        """
        UPDATE building_summaries
        SET
            rent_yen_min=NULL,
            rent_yen_max=NULL,
            area_sqm_min=NULL,
            area_sqm_max=NULL,
            layout_types_json=NULL,
            move_in_dates_json=NULL,
            vacancy_count=0,
            last_updated=NULL,
            updated_at=CURRENT_TIMESTAMP
        """
    )

    existing = {
        row["building_key"]: row
        for row in conn.execute(
            "SELECT building_key, name, raw_name, address FROM building_summaries"
        ).fetchall()
    }
    rows = conn.execute(
        """
        SELECT building_key, name, address, rent_yen, area_sqm, layout, move_in_date, updated_at
        FROM listings
        ORDER BY id DESC
        """
    ).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        canonical_key = alias_map.get(row["building_key"], row["building_key"])
        grouped.setdefault(canonical_key, []).append(row)

    count = 0
    for building_key, items in grouped.items():
        rents = [r["rent_yen"] for r in items if r["rent_yen"] is not None]
        areas = [r["area_sqm"] for r in items if r["area_sqm"] is not None]
        layouts = sorted({normalize_text(r["layout"]) for r in items if r["layout"]})
        move_in_dates = sorted({normalize_text(r["move_in_date"]) for r in items if r["move_in_date"]})
        latest = max((r["updated_at"] for r in items if r["updated_at"]), default=None)
        existing_row = existing.get(building_key)
        summary_name = items[0]["name"] or (existing_row["name"] if existing_row else "")
        summary_address = items[0]["address"] or (existing_row["address"] if existing_row else "")
        summary_raw_name = (existing_row["raw_name"] if existing_row and existing_row["raw_name"] else summary_name)

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
        count += 1

    conn.commit()
    conn.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--alias-csv", default="")
    args = parser.parse_args()
    n = rebuild(args.db_path, alias_csv=args.alias_csv)
    print(f"rebuilt building_summaries: {n}")


if __name__ == "__main__":
    main()
