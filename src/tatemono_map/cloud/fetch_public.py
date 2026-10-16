"""Pages downloads only a validated public artifact, never the private master."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.public_db import validate_public
from tatemono_map.cloud.storage import GCSStore, validate_head


def fetch(store, output: Path, marker: Path) -> dict:
    head, _ = store.read_head()
    validate_head(head)
    report = head["report"]
    valid_pdf = report.get("acquisition_status") == "pdf_verified" and report.get("pdf_count", 0) > 0 and report.get("parsed_rows", 0) > 0
    valid_zero = report.get("acquisition_status") == "confirmed_zero" and report.get("pdf_count") == report.get("parsed_rows") == 0
    if report.get("bootstrap") or not report.get("proof") or not (valid_pdf or valid_zero) or report.get("parsed_rows") != report.get("attached_rows"):
        raise CollectionError("release_has_no_successful_collection_proof")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_suffix(".download")
    store.download(head["public"], staged)
    counts = validate_public(staged)
    if counts != head["report"]["public_counts"]:
        raise CollectionError("public_counts_do_not_match_release")
    os.replace(staged, output)
    proof_fields = ("building_key", "vacancy_count", "rent_yen_min", "rent_yen_max")
    proof = [{key: row[key] for key in proof_fields} for row in report["proof"]]
    public_marker = {"schema": 1, "run_id": head["run_id"], "public_sha256": head["public"]["sha256"], "source_commit": head["source_commit"], "counts": counts, "proof": proof}
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(public_marker, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return public_marker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", type=Path, default=Path("data/public/public.sqlite3"))
    parser.add_argument("--marker", type=Path, default=Path("work/cloud_release.json"))
    args = parser.parse_args()
    try:
        marker = fetch(GCSStore(args.bucket), args.output, args.marker)
        print(f"validated_public_release={marker['run_id']}")
    except Exception:
        raise SystemExit("validated public release unavailable; refusing Pages deployment") from None


if __name__ == "__main__":
    main()
