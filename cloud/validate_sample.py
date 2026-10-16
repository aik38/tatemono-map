#!/usr/bin/env python3
"""Private sample validation only. Never ingests/publishes the supplied all-area PDF."""
import argparse
import json
import re
from pathlib import Path

from pypdf import PdfReader
from tatemono_map.cli.pdf_batch_run import UlucksParser, qc_check
from tatemono_map.cloud.public_db import sha256


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("work/sample-validation.json"))
    args = p.parse_args()
    reader = PdfReader(args.pdf)
    text_lengths = [len(page.extract_text() or "") for page in reader.pages]
    frame = UlucksParser().parse(args.pdf).df
    wards = frame["address"].str.extract(r"(小倉北区|小倉南区|八幡東区|八幡西区|若松区|戸畑区|門司区)")[0].value_counts().to_dict()
    result = {
        "purpose": "provided_all_area_sample_parser_validation_only",
        "live_collection": False, "master_updated": False, "published": False,
        "pdf_sha256": sha256(args.pdf), "pdf_bytes": args.pdf.stat().st_size,
        "pages": len(reader.pages), "text_extractable_pages": sum(n > 0 for n in text_lengths),
        "parsed_rows": len(frame), "qc_reasons": qc_check(frame, "ulucks"),
        "rows_by_area": {str(k): int(v) for k, v in wards.items()},
        "missing_rent": int(frame["rent_man"].isna().sum()), "missing_area_sqm": int(frame["area_sqm"].isna().sum()),
        "duplicate_units": int(frame.duplicated(["building_name", "address", "room"]).sum()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
