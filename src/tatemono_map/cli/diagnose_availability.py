from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from tatemono_map.normalize.listing_fields import normalize_availability


def _clean(value: str | None) -> str:
    return (value or "").strip()


def analyze_csv(csv_path: Path) -> None:
    counts: dict[str, Counter] = defaultdict(Counter)
    samples: list[tuple[str, str, int, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            category = _clean(row.get("category")) or "(empty)"
            raw = _clean(row.get("availability_raw"))
            inferred_immediate, _, inferred_date = normalize_availability(raw, row.get("updated_at"), category)

            c = counts[category]
            c["rows"] += 1
            if raw:
                c["availability_raw_filled"] += 1
            if inferred_immediate:
                c["inferred_immediate_count"] += 1
            if inferred_date:
                c["inferred_date_count"] += 1

            if len(samples) < 20:
                samples.append((category, raw, 1 if inferred_immediate else 0, inferred_date or ""))

    print("[CSV] per-category counts")
    for category in sorted(counts):
        c = counts[category]
        print(
            f"- {category}: rows={c['rows']} availability_raw_filled={c['availability_raw_filled']} "
            f"inferred_immediate_count={c['inferred_immediate_count']} inferred_date_count={c['inferred_date_count']}"
        )

    print("\n[CSV] sample rows (max 20)")
    print("category	availability_raw	inferred_immediate	inferred_date")
    for category, raw, immediate, inferred_date in samples:
        print(f"{category}	{raw}	{immediate}	{inferred_date}")


def analyze_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN TRIM(COALESCE(building_availability_label,'')) <> '' THEN 1 ELSE 0 END) AS label_filled,
          COALESCE(SUM(vacancy_count), 0) AS vacancy_sum
        FROM building_summaries
        """
    ).fetchone()

    summary_samples = conn.execute(
        """
        SELECT name, building_availability_label, vacancy_count
        FROM building_summaries
        ORDER BY vacancy_count DESC, name
        LIMIT 20
        """
    ).fetchall()
    conn.close()

    print("\n[DB] counts")
    print(f"- label_filled={row['label_filled']} vacancy_sum={row['vacancy_sum']}")

    print("\n[DB] building_summaries sample rows (max 20)")
    print("name	building_availability_label	vacancy_count")
    for r in summary_samples:
        print(f"{_clean(r['name'])}	{_clean(r['building_availability_label'])}	{r['vacancy_count']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    analyze_csv(Path(args.csv))
    analyze_db(Path(args.db))


if __name__ == "__main__":
    main()
