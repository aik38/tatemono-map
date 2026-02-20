from __future__ import annotations

import argparse
import csv
from pathlib import Path

from tatemono_map.buildings_master.from_sources import _stable_key, normalize_address_jp, normalize_building_name
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


def _compute_stable_building_key(name: str, address: str) -> str:
    normalized_name = normalize_building_name(name or "")
    normalized_address = normalize_address_jp(address or "")
    return _stable_key(normalized_address, normalized_name)


def _load_buildings_master_rows(buildings_master_csv: str) -> list[dict[str, str]]:
    path = Path(buildings_master_csv)
    if not path.exists():
        raise FileNotFoundError(f"buildings master csv not found: {buildings_master_csv}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV header missing: {buildings_master_csv}")
        return [{k: (v or "") for k, v in row.items()} for row in reader]


def rebuild(db_path: str, alias_csv: str = "", buildings_master_csv: str = "") -> int:
    conn = connect(db_path)
    alias_map = _load_alias_map(alias_csv)
    seeded_buildings = 0

    if buildings_master_csv:
        conn.execute("DELETE FROM building_summaries")
        master_rows = _load_buildings_master_rows(buildings_master_csv)
        seeded: set[str] = set()
        for row in master_rows:
            raw_key = (row.get("building_key") or "").strip()
            name = (row.get("building_name") or row.get("name") or "").strip()
            address = (row.get("address") or "").strip()
            stable_key = raw_key or _compute_stable_building_key(name, address)
            canonical_key = alias_map.get(stable_key, stable_key)
            if not canonical_key or canonical_key in seeded:
                continue

            replace_building_summary(
                conn,
                {
                    "building_key": canonical_key,
                    "name": name,
                    "raw_name": name,
                    "address": address,
                    "rent_yen_min": None,
                    "rent_yen_max": None,
                    "area_sqm_min": None,
                    "area_sqm_max": None,
                    "layout_types": [],
                    "move_in_dates": [],
                    "vacancy_count": 0,
                    "last_updated": None,
                },
            )
            seeded.add(canonical_key)
        seeded_buildings = len(seeded)
    else:
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
        stable_key = _compute_stable_building_key(row["name"] or "", row["address"] or "")
        canonical_key = alias_map.get(stable_key, stable_key)
        if not canonical_key:
            continue
        grouped.setdefault(canonical_key, []).append(row)

    count = 0
    for building_key, items in grouped.items():
        rents = [r["rent_yen"] for r in items if r["rent_yen"] is not None]
        areas = [r["area_sqm"] for r in items if r["area_sqm"] is not None]
        layouts = sorted({normalize_text(r["layout"]) for r in items if r["layout"]})
        move_in_dates = sorted({normalize_text(r["move_in_date"]) for r in items if r["move_in_date"]})
        latest = max((r["updated_at"] for r in items if r["updated_at"]), default=None)
        existing_row = existing.get(building_key)
        summary_name = (existing_row["name"] if existing_row and existing_row["name"] else items[0]["name"])
        summary_address = (existing_row["address"] if existing_row and existing_row["address"] else items[0]["address"])
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

    total = conn.execute("SELECT COUNT(*) AS c FROM building_summaries").fetchone()["c"]
    print(
        "seeded_buildings={} listings={} distinct_stable_buildings_in_listings={} building_summaries_total={}".format(
            seeded_buildings,
            len(rows),
            len(grouped),
            total,
        )
    )

    conn.commit()
    conn.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--alias-csv", default="")
    parser.add_argument("--buildings-master-csv", default="")
    args = parser.parse_args()
    n = rebuild(args.db_path, alias_csv=args.alias_csv, buildings_master_csv=args.buildings_master_csv)
    print(f"rebuilt building_summaries: {n}")


if __name__ == "__main__":
    main()
