from __future__ import annotations

import os

from tatemono_map.normalize.building_summaries import rebuild


def main() -> int:
    db_path = os.getenv("SQLITE_DB_PATH", "data/tatemono_map.sqlite3")
    count = rebuild(db_path)
    print(f"rebuilt building_summaries: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
