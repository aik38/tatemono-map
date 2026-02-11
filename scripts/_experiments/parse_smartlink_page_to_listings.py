from __future__ import annotations

import argparse

from tatemono_map.parse.smartlink_page import parse_and_upsert


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    args = parser.parse_args()
    n = parse_and_upsert(args.db_path)
    print(f"upserted listings from smartlink_page: {n}")


if __name__ == "__main__":
    main()
