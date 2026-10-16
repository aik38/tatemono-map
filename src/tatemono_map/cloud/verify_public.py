"""Compare the existing renderer's JSON and production JSON with release proof."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

SITE = "https://www.tatemono-map.com"


def compare(marker: dict, rows: list[dict]) -> None:
    if not marker.get("proof"):
        raise ValueError("release_has_no_collection_proof")
    by_id = {str(row["id"]): row for row in rows}
    for proof in marker["proof"]:
        row = by_id.get(str(proof["building_key"]))
        if row is None:
            raise ValueError("updated_building_missing_from_public_json")
        for public_key, proof_key in (("vacancy_count", "vacancy_count"), ("rent_min", "rent_yen_min"), ("rent_max", "rent_yen_max")):
            if row.get(public_key) != proof.get(proof_key):
                raise ValueError("updated_building_differs_from_verified_database")


def get_json(path: str, run: str):
    request = Request(f"{SITE}/{path}?release={run}", headers={"Cache-Control": "no-cache", "User-Agent": "tatemono-cloud-verification"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def verify_site(expected: dict, attempts: int = 10, interval: int = 15):
    for attempt in range(attempts):
        try:
            actual = get_json("cloud_release.json", expected["run_id"])
            if actual["run_id"] != expected["run_id"] or actual["public_sha256"] != expected["public_sha256"]:
                raise ValueError("production_release_marker_not_updated")
            compare(expected, get_json("data/buildings.json", expected["run_id"]))
            return
        except Exception:
            if attempt + 1 == attempts:
                raise ValueError("production_release_verification_failed") from None
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--marker", type=Path, default=Path("work/cloud_release.json"))
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    marker = json.loads(args.marker.read_text(encoding="utf-8"))
    if args.dist:
        compare(marker, json.loads((args.dist / "data/buildings.json").read_text(encoding="utf-8")))
    if args.production:
        verify_site(marker)
    print(f"verified_release={marker['run_id']}")


if __name__ == "__main__":
    main()
