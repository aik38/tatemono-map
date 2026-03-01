from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _is_filled(value: str | None) -> bool:
    return bool(_clean(value))


def analyze_csv(csv_path: Path) -> None:
    counts: dict[str, Counter] = defaultdict(Counter)
    raw_values: dict[str, Counter] = defaultdict(Counter)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            category = _clean(row.get("category")) or "(empty)"
            counts[category]["rows"] += 1
            if _is_filled(row.get("availability_raw")):
                counts[category]["availability_raw_filled"] += 1
                raw_values[category][_clean(row.get("availability_raw"))] += 1
            if _is_filled(row.get("availability_date")):
                counts[category]["availability_date_filled"] += 1
            if _clean(row.get("availability_flag_immediate")) == "1":
                counts[category]["immediate_flag_1"] += 1

    print("[CSV] availability summary by category")
    for category in sorted(counts):
        c = counts[category]
        print(
            f"- {category}: rows={c['rows']} availability_raw_filled={c['availability_raw_filled']} "
            f"availability_date_filled={c['availability_date_filled']} immediate_flag_1={c['immediate_flag_1']}"
        )

    print("\n[CSV] availability_raw top30 by category")
    for category in sorted(raw_values):
        print(f"- {category}")
        for value, n in raw_values[category].most_common(30):
            print(f"  {n:>4}  {value}")


def _json_array_len(value: str | None) -> int:
    text = _clean(value)
    if not text:
        return 0
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return 0
    return len(decoded) if isinstance(decoded, list) else 0


def analyze_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    label_count = conn.execute(
        "SELECT COUNT(*) AS c FROM building_summaries WHERE TRIM(COALESCE(building_availability_label,'')) <> ''"
    ).fetchone()["c"]
    rows = conn.execute("SELECT move_in_dates_json FROM building_summaries").fetchall()
    true_non_empty = sum(1 for row in rows if _json_array_len(row["move_in_dates_json"]) > 0)
    dist = Counter((_clean(row["move_in_dates_json"]) or "<null_or_empty>") for row in rows)
    conn.close()

    print("\n[DB] building_summaries")
    print(f"- non_empty_building_availability_label={label_count}")
    print(f"- move_in_dates_json_true_non_empty_array={true_non_empty}")
    print("- move_in_dates_json_raw_distribution_top30")
    for value, n in dist.most_common(30):
        print(f"  {n:>4}  {value}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    analyze_csv(Path(args.csv))
    analyze_db(Path(args.db))


if __name__ == "__main__":
    main()
