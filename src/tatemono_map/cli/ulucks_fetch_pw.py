from __future__ import annotations

import argparse
import os

from tatemono_map.ingest.ulucks_playwright import fetch_seed, init_auth_state


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tatemono_map.cli.ulucks_fetch_pw")
    parser.add_argument("--url", action="append", help="smartlink seed URL (can be repeated)")
    parser.add_argument("--auth-file", default="secrets/ulucks_auth.json")
    parser.add_argument("--db", default=os.getenv("SQLITE_DB_PATH", "data/tatemono_map.sqlite3"))
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--init-auth", action="store_true")
    args = parser.parse_args()

    if args.init_auth:
        init_auth_state(args.auth_file)
        print(f"saved_auth_state={args.auth_file}")
        return

    if not args.url:
        raise SystemExit("--url is required unless --init-auth is provided")

    total = 0
    for seed in args.url:
        saved = fetch_seed(seed, args.auth_file, args.db, max_pages=args.max_pages)
        total += saved
        print(f"seed_saved_pages={saved} url={seed}")
    print(f"total_saved_pages={total}")


if __name__ == "__main__":
    main()
