from __future__ import annotations

import argparse

from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.normalize.building_summaries import rebuild


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--building-key", default="demo")
    args = parser.parse_args()

    conn = connect(args.db)
    upsert_listing(
        conn,
        ListingRecord(
            name="デモ建物",
            address="東京都新宿区1-1-1",
            rent_yen=50000,
            area_sqm=20.0,
            layout="1K",
            updated_at="2026-01-01",
            source_kind="stub",
            source_url="stub://demo",
            move_in_date="即入居",
        ),
    )
    conn.close()
    rebuild(args.db)


if __name__ == "__main__":
    main()
