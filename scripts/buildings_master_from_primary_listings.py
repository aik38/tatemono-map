from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

DEFAULT_IN = "tmp/manual/inputs/primary_listings.csv"
DEFAULT_OUT = "tmp/manual/outputs/buildings_master_primary.csv"


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _norm_key(text: str) -> str:
    return _normalize_space(text).replace("　", " ")


def _key(row: dict[str, str], *, addr_only_fallback: bool) -> tuple[str, str]:
    address = _norm_key(row.get("address", ""))
    name = _norm_key(row.get("building_name", ""))
    if addr_only_fallback and not name:
        return (address, "")
    return (address, name)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="primary_listings.csv（空室行ベース）から建物マスター（1行=1建物）を作成"
    )
    parser.add_argument("--in", dest="input_csv", default=DEFAULT_IN, help=f"入力CSV（既定: {DEFAULT_IN}）")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"出力CSV（既定: {DEFAULT_OUT}）")
    parser.add_argument(
        "--addr-only-fallback",
        action="store_true",
        help="building_name 欠損時は address のみで同一建物として集約する",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    in_path = Path(args.input_csv)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with in_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("入力CSVにヘッダーがありません")
        if "address" not in reader.fieldnames or "building_name" not in reader.fieldnames:
            raise ValueError("入力CSVに address/building_name 列が必要です")

        observed_cols: set[str] = set(reader.fieldnames)
        grouped: dict[tuple[str, str], dict[str, object]] = {}

        for row in reader:
            normalized = {k: (v or "") for k, v in row.items()}
            normalized["address"] = _normalize_space(normalized.get("address", ""))
            normalized["building_name"] = _normalize_space(normalized.get("building_name", ""))
            k = _key(normalized, addr_only_fallback=args.addr_only_fallback)
            if not k[0]:
                continue

            if k not in grouped:
                normalized["listing_rows"] = 0
                grouped[k] = normalized

            current = grouped[k]
            current["listing_rows"] = int(current["listing_rows"]) + 1

            for col, value in normalized.items():
                if col in {"address", "building_name"}:
                    continue
                if not current.get(col) and value:
                    current[col] = value

    preferred = ["building_name", "address", "listing_rows"]
    remaining = [c for c in sorted(observed_cols) if c not in preferred]
    fieldnames = preferred + remaining

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in sorted(
            grouped.values(),
            key=lambda r: (_norm_key(str(r.get("address", ""))), _norm_key(str(r.get("building_name", "")))),
        ):
            writer.writerow(record)

    print(f"[DONE] unique_buildings={len(grouped)} -> {out_path}")


if __name__ == "__main__":
    main()
