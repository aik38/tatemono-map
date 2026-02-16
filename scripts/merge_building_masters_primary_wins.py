from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


DEFAULT_OUT = "tmp/manual/out/buildings_master_all.csv"


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _norm(text: str) -> str:
    return _normalize_space(text).replace("　", " ")


def _building_name(row: dict[str, str]) -> str:
    return row.get("building_name", "") or row.get("mansion_name", "")


def _load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV header missing: {path}")
        rows = [{k: (v or "") for k, v in row.items()} for row in reader]
        return rows, list(reader.fieldnames)


def _key(row: dict[str, str]) -> tuple[str, str]:
    return (_norm(_building_name(row)), _norm(row.get("address", "")))


def _address_index(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        addr = _norm(row.get("address", ""))
        if not addr:
            continue
        counts[addr] = counts.get(addr, 0) + 1
    return counts


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="建物マスターCSV同士を primary wins でマージ")
    parser.add_argument("--primary", required=True, help="既存の統合済み建物マスター")
    parser.add_argument("--secondary", required=True, help="追加候補の建物マスター")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"出力CSV（既定: {DEFAULT_OUT}）")
    parser.add_argument(
        "--addr-only-fallback",
        action="store_true",
        help="secondary 側が同一住所で、primary 側その住所が1件のみなら重複とみなして追加しない",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    primary_path = Path(args.primary)
    secondary_path = Path(args.secondary)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    primary_rows, primary_headers = _load_rows(primary_path)
    secondary_rows, secondary_headers = _load_rows(secondary_path)

    for path, headers in [(primary_path, primary_headers), (secondary_path, secondary_headers)]:
        if "address" not in headers:
            raise ValueError(f"address 列がありません（建物マスター前提）: {path}")
        if "building_name" not in headers and "mansion_name" not in headers:
            raise ValueError(
                f"building_name も mansion_name もありません（建物マスター前提）: {path}"
            )

    merged_headers = list(primary_headers)
    for h in secondary_headers:
        if h not in merged_headers:
            merged_headers.append(h)

    merged_rows = list(primary_rows)
    existing_keys = {_key(r) for r in primary_rows}
    address_counts = _address_index(primary_rows)

    appended = 0
    skipped_exact = 0
    skipped_fallback = 0

    for row in secondary_rows:
        key = _key(row)
        if key in existing_keys:
            skipped_exact += 1
            continue

        if args.addr_only_fallback:
            addr = _norm(row.get("address", ""))
            if addr and address_counts.get(addr, 0) == 1:
                skipped_fallback += 1
                continue

        merged_rows.append(row)
        existing_keys.add(key)
        addr = _norm(row.get("address", ""))
        if addr:
            address_counts[addr] = address_counts.get(addr, 0) + 1
        appended += 1

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=merged_headers)
        writer.writeheader()
        for row in merged_rows:
            writer.writerow({h: row.get(h, "") for h in merged_headers})

    print(
        f"[DONE] primary={len(primary_rows)} secondary={len(secondary_rows)} "
        f"appended={appended} skipped_exact={skipped_exact} skipped_fallback={skipped_fallback} -> {out_path}"
    )


if __name__ == "__main__":
    main()
