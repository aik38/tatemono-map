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
    m = re.search(r"(\d+(?:\.\d+)?)\s*万円", normalized)
    if m:
        return m.group(1)
    yen = re.search(r"(\d+)\s*円", normalized)
    if not yen:
        return ""
    value = int(yen.group(1)) / 10000
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _extract_area(text: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2)", _clean(text))
    return m.group(1) if m else ""


def _build_raw_block(row: dict[str, str]) -> str:
    parts = [
        f"種類:{_clean(row.get('kind'))}",
        f"市区:{_clean(row.get('ward'))}",
        f"価格賃料:{_clean(row.get('price_or_rent_text'))}",
        f"間取り:{_clean(row.get('layout_text'))}",
        f"面積:{_clean(row.get('area_text'))}",
        f"所在階:{_clean(row.get('floor_text'))}",
        f"詳細URL:{_clean(row.get('detail_url'))}",
        f"一覧URL:{_clean(row.get('page_url'))}",
    ]
    return " | ".join(p for p in parts if not p.endswith(":"))


def _evidence_id(row: dict[str, str]) -> str:
    detail_url = _clean(row.get("detail_url"))
    if detail_url:
        return f"mansion_review:{detail_url}"
    digest_input = "|".join(_clean(row.get(k)) for k in ("kind", "building_name", "address", "city_page", "price_or_rent_text"))
    digest = hashlib.sha1(digest_input.encode("utf-8")).hexdigest()[:16]
    return f"mansion_review:list:{digest}"


def convert(input_csv: Path, output_csv: Path, updated_at: str | None) -> int:
    updated = updated_at or _parse_updated_at_from_filename(input_csv)
    written = 0
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    with input_csv.open("r", encoding="utf-8-sig", newline="") as in_fh, output_csv.open(
        "w", encoding="utf-8-sig", newline=""
    ) as out_fh:
        reader = csv.DictReader(in_fh)
        writer = csv.DictWriter(out_fh, fieldnames=list(MASTER_COLUMNS))
        writer.writeheader()

        for src in reader:
            kind = _clean(src.get("kind")).lower()
            if kind not in {"mansion", "chintai"}:
                continue

            writer.writerow(
                {
                    "page": _clean(src.get("detail_url")) or _clean(src.get("page_url")),
                    "category": kind,
                    "updated_at": updated,
                    "building_name": _clean(src.get("building_name")),
                    "room": "",
                    "address": _clean(src.get("address")),
                    "rent_man": _extract_man_value(src.get("price_or_rent_text") or ""),
                    "fee_man": "",
                    "floor": _clean(src.get("floor_text")),
                    "layout": _clean(src.get("layout_text")),
                    "area_sqm": _extract_area(src.get("area_text") or ""),
                    "age_years": "",
                    "structure": "",
                    "built_year_month": "",
                    "built_age_years": "",
                    "availability_raw": "",
                    "availability_date": "",
                    "availability_flag_immediate": "",
                    "built_raw": "",
                    "structure_raw": "",
                    "raw_block": _build_raw_block(src),
                    "evidence_id": _evidence_id(src),
                }
            )
            written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert mansion_review_list CSV to ingest_master_import-compatible CSV")
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--updated-at", default="")
    args = parser.parse_args()

    input_csv = Path(args.input_csv)
    output_csv = Path(args.output_csv)
    count = convert(input_csv, output_csv, args.updated_at or None)
    print(f"converted_rows={count} output={output_csv}")


if __name__ == "__main__":
    main()
