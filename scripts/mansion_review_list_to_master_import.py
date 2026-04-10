from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

MASTER_COLUMNS = (
    "page",
    "category",
    "updated_at",
    "building_name",
    "room",
    "address",
    "rent_man",
    "fee_man",
    "floor",
    "layout",
    "area_sqm",
    "availability_raw",
    "built_raw",
    "age_years",
    "structure",
    "built_year_month",
    "built_age_years",
    "availability_date",
    "availability_flag_immediate",
    "structure_raw",
    "raw_block",
    "evidence_id",
)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_updated_at_from_filename(path: Path) -> str:
    m = re.search(r"(\d{8})_(\d{6})", path.name)
    if not m:
        return datetime.now().strftime("%Y/%m/%d %H:%M")
    dt = datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
    return dt.strftime("%Y/%m/%d %H:%M")


def _extract_man_value(text: str) -> str:
    normalized = _clean(text).replace(",", "")
    if not normalized:
        return ""

    man = re.search(r"(\d+(?:\.\d+)?)\s*万円", normalized)
    if man:
        return man.group(1)

    yen = re.search(r"(\d+)\s*円", normalized)
    if yen:
        value = int(yen.group(1)) / 10000
        return f"{value:.4f}".rstrip("0").rstrip(".")

    return ""


def _extract_area_sqm(text: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2)", _clean(text))
    return m.group(1) if m else ""


def _simple_layout(value: str | None) -> str:
    layout = _clean(value)
    return "" if len(layout) > 40 else layout


def _build_raw_block(row: dict[str, str]) -> str:
    fields = [
        ("種類", row.get("kind")),
        ("市区", row.get("ward")),
        ("価格賃料", row.get("price_or_rent_text")),
        ("管理費", row.get("fee_text")),
        ("坪単価", row.get("tsubo_unit_price_text")),
        ("敷金", row.get("deposit_text")),
        ("礼金", row.get("key_money_text")),
        ("専有面積", row.get("area_text")),
        ("間取り", row.get("layout_text")),
        ("所在階", row.get("floor_text")),
        ("向き", row.get("direction_text")),
        ("住所", row.get("address")),
        ("交通", row.get("access_text")),
        ("築年数", row.get("built_text")),
        ("階建て", row.get("building_floor_count_text")),
        ("総戸数", row.get("total_units_text")),
        ("詳細URL", row.get("detail_url")),
        ("一覧URL", row.get("page_url")),
    ]
    return " | ".join(f"{k}:{_clean(v)}" for k, v in fields if _clean(v))


def _evidence_id(row: dict[str, str]) -> str:
    detail_url = _clean(row.get("detail_url"))
    payload = "|".join(
        _clean(row.get(k))
        for k in (
            "kind",
            "price_or_rent_text",
            "fee_text",
            "tsubo_unit_price_text",
            "deposit_text",
            "key_money_text",
            "area_text",
            "layout_text",
            "floor_text",
            "direction_text",
        )
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    if detail_url:
        return f"mansion_review:{detail_url}#l={digest}"
    return f"mansion_review:list:{digest}"


def convert(input_csv: Path, output_csv: Path, updated_at: str | None) -> int:
    updated = updated_at or _parse_updated_at_from_filename(input_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with input_csv.open("r", encoding="utf-8-sig", newline="") as in_fh, output_csv.open(
        "w", encoding="utf-8-sig", newline=""
    ) as out_fh:
        reader = csv.DictReader(in_fh)
        writer = csv.DictWriter(out_fh, fieldnames=list(MASTER_COLUMNS))
        writer.writeheader()

        for row in reader:
            kind = _clean(row.get("kind")).lower()
            if kind not in {"chintai", "mansion"}:
                continue
            writer.writerow(
                {
                    "page": _clean(row.get("detail_url")) or _clean(row.get("page_url")),
                    "category": kind,
                    "updated_at": updated,
                    "building_name": _clean(row.get("building_name")),
                    "room": "",
                    "address": _clean(row.get("address")),
                    "rent_man": _extract_man_value(_clean(row.get("price_or_rent_text"))),
                    "fee_man": _extract_man_value(_clean(row.get("fee_text"))) if kind == "chintai" else "",
                    "floor": _clean(row.get("floor_text")),
                    "layout": _simple_layout(row.get("layout_text")),
                    "area_sqm": _extract_area_sqm(_clean(row.get("area_text"))),
                    "availability_raw": "",
                    "built_raw": _clean(row.get("built_text")),
                    "age_years": "",
                    "structure": "",
                    "built_year_month": "",
                    "built_age_years": "",
                    "availability_date": "",
                    "availability_flag_immediate": "",
                    "structure_raw": "",
                    "raw_block": _build_raw_block(row),
                    "evidence_id": _evidence_id(row),
                }
            )
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert mansion_review list CSV to master_import CSV")
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--updated-at", default="")
    args = parser.parse_args()

    converted = convert(Path(args.input_csv), Path(args.output_csv), args.updated_at or None)
    print(f"converted_rows={converted} output={args.output_csv}")


if __name__ == "__main__":
    main()
