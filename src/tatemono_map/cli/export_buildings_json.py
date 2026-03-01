from __future__ import annotations

import argparse

from tatemono_map.render.build import export_buildings_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--format", choices=("v2min", "legacy"), default="v2min")
    args = parser.parse_args()

    export_buildings_json(db_path=args.db, output_path=args.out, fmt=args.format)


if __name__ == "__main__":
    main()
