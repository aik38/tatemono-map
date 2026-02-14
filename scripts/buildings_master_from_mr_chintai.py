from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

DEFAULT_OUT = "buildings_master_from_mr_chintai.csv"


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _norm_key(text: str) -> str:
    return _normalize_space(text).replace("　", " ")


def _looks_like_noise(building_name: str, address: str) -> bool:
    b = _normalize_space(building_name)
    a = _normalize_space(address)
    joined = f"{b} {a}".lower()
    if not b and not a:
        return True

    noise_keywords = [
        "ランキング",
        "口コミ",
        "人気",
        "もっと見る",
        "都道府県から探す",
        "路線から探す",
        "条件を変更",
        "検索結果",
    ]
    if any(k in joined for k in noise_keywords):
        return True

    if re.fullmatch(r"[\d,]+件", b):
        return True

    return False


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MR賃貸CSV（空室行ベース）から建物マスターを重複排除して作成"
    )
    parser.add_argument("--in", dest="input_csv", required=True, help="入力CSV（mansion_review_fetch_chintai 出力）")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"出力CSV（既定: {DEFAULT_OUT}）")
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

        grouped: dict[tuple[str, str], dict[str, object]] = {}
        observed_cols: set[str] = set(reader.fieldnames)

        for row in reader:
            building_name = _normalize_space(row.get("building_name", ""))
            address = _normalize_space(row.get("address", ""))

            if _looks_like_noise(building_name, address):
                continue

            key = (_norm_key(building_name), _norm_key(address))
            if key not in grouped:
                kept = {k: (v or "") for k, v in row.items()}
                kept["building_name"] = building_name
                kept["address"] = address
                kept["vacancy_rows"] = 0
                grouped[key] = kept

            current = grouped[key]
            current["vacancy_rows"] = int(current["vacancy_rows"]) + 1

            for col, value in row.items():
                if col in {"building_name", "address"}:
                    continue
                if not current.get(col) and value:
                    current[col] = value

    preferred = ["building_name", "address", "vacancy_rows"]
    remaining = [c for c in sorted(observed_cols) if c not in preferred]
    fieldnames = preferred + remaining

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in sorted(grouped.values(), key=lambda r: (_norm_key(str(r.get("building_name", ""))), _norm_key(str(r.get("address", ""))))):
            writer.writerow(record)

    print(f"[DONE] unique_buildings={len(grouped)} -> {out_path}")


if __name__ == "__main__":
    main()
