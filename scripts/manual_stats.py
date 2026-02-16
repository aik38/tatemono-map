from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _norm(text: str) -> str:
    return _normalize_space(text).replace("　", " ")


def _name_value(row: dict[str, str]) -> str:
    return row.get("building_name", "") or row.get("mansion_name", "")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CSVの件数・建物ユニーク数・欠損数を表示")
    parser.add_argument("csv_path", help="集計対象CSV")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    csv_path = Path(args.csv_path)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSVにヘッダーがありません")

        rows = [{k: (v or "") for k, v in row.items()} for row in reader]

    unique_buildings = {
        (_norm(row.get("address", "")), _norm(_name_value(row)))
        for row in rows
        if _norm(row.get("address", "")) or _norm(_name_value(row))
    }

    print(f"csv={csv_path}")
    print(f"rows={len(rows)}")
    print(f"unique_buildings(address+name)={len(unique_buildings)}")

    missing_cols = [
        col
        for col in ["address", "building_name", "mansion_name"]
        if col in (reader.fieldnames or [])
    ]
    for col in missing_cols:
        missing = sum(1 for row in rows if not _norm(row.get(col, "")))
        print(f"missing_{col}={missing}")


if __name__ == "__main__":
    main()
