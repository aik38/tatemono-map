"""Pages downloads only a validated public artifact, never the private master."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.public_db import validate_public, rendered_ids, id_fingerprint
from tatemono_map.cloud.storage import GCSStore, validate_head


def accounted_collection(report):
    if report.get('integration_contract')!='ulucks-partial-v1':
        return report.get('parsed_rows')==report.get('attached_rows')
    counts=report.get('row_counts',{})
    allowed={'accepted_existing','accepted_new','held','anomaly','duplicate'}
    return (isinstance(counts,dict) and set(counts)<=allowed
        and all(type(value) is int and value>=0 for value in counts.values())
        and sum(counts.values())==report.get('parsed_rows')
        and counts.get('accepted_existing',0)+counts.get('accepted_new',0)==report.get('attached_rows'))


def validate_collection_proof(report):
    valid_pdf = report.get("acquisition_status") == "pdf_verified" and report.get("pdf_count", 0) > 0 and report.get("parsed_rows", 0) > 0
    valid_zero = report.get("acquisition_status") == "confirmed_zero" and report.get("pdf_count") == report.get("parsed_rows") == 0
    if report.get("bootstrap") or not report.get("proof") or not (valid_pdf or valid_zero) or not accounted_collection(report):
        raise CollectionError("release_has_no_successful_collection_proof")


def fetch(store, output: Path, marker: Path) -> dict:
    head, _ = store.read_head()
    validate_head(head)
    report = head["report"]
    validate_collection_proof(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_suffix(".download")
    store.download(head["public"], staged)
    counts = validate_public(staged)
    if counts != head["report"]["public_counts"]:
        raise CollectionError("public_counts_do_not_match_release")
    os.replace(staged, output)
    proof_fields = ("building_key", "vacancy_count", "rent_yen_min", "rent_yen_max", "area_sqm_min", "area_sqm_max", "layout_types", "maint_yen_min", "maint_yen_max")
    proof = [{key: row[key] for key in proof_fields if key in row} for row in report["proof"]]
    public_marker = {"schema": 1, "run_id": head["run_id"], "public_sha256": head["public"]["sha256"], "source_commit": head["source_commit"], "counts": counts, "proof": proof}
    ids = rendered_ids(output)
    public_marker.update(rendered_buildings=len(ids), rendered_ids_sha256=id_fingerprint(ids))
    if report.get('release_kind') == 'publication_only':
        public_marker.update(release_kind='publication_only', collection_run_id=report['collection_run_id'],
            newly_acquired_pdf_count=0)
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
