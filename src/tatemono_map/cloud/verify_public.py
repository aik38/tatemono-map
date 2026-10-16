"""Compare the existing renderer's JSON and production JSON with release proof."""
from __future__ import annotations

import argparse
import json
import html
import re
import time
from pathlib import Path
from urllib.parse import quote, urlsplit
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
        for public_key, proof_key in (('area_min','area_sqm_min'),('area_max','area_sqm_max'),('room_types','layout_types'),('maint_min','maint_yen_min'),('maint_max','maint_yen_max')):
            if proof_key in proof and row.get(public_key) != proof[proof_key]:
                raise ValueError('updated_building_terms_differ_from_verified_database')


def get_json(path: str, run: str):
    request = Request(f"{SITE}/{path}?release={run}", headers={"Cache-Control": "no-cache", "User-Agent": "tatemono-cloud-verification"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def verify_detail_pages(expected: dict, rows: list[dict]) -> list[str]:
    """Check representative real HTML pages in addition to all JSON proof rows."""
    by_id = {str(row['id']): row for row in rows}
    proofs = sorted(expected['proof'], key=lambda p: not bool(p['vacancy_count']))[:3]
    verified = []
    for proof in proofs:
        row = by_id[str(proof['building_key'])]
        filename = row.get('detail_filename', '')
        if not filename.endswith('.html') or '/' in filename or '\\' in filename:
            raise ValueError('production_detail_filename_invalid')
        url = SITE + '/b/' + quote(filename)
        request = Request(url + '?release=' + expected['run_id'], headers={'Cache-Control':'no-cache', 'User-Agent':'tatemono-cloud-verification'})
        with urlopen(request, timeout=30) as response:
            if response.status != 200 or urlsplit(response.geturl()).netloc != urlsplit(SITE).netloc:
                raise ValueError('production_detail_page_unavailable')
            body = response.read().decode('utf-8')
        text = re.sub(r'\s+', '', html.unescape(re.sub(r'<[^>]+>', ' ', body)))
        if re.sub(r'\s+', '', row['name']) not in text:
            raise ValueError('production_detail_identity_mismatch')
        if proof['vacancy_count']:
            lo, hi = proof['rent_yen_min'], proof['rent_yen_max']
            rent = f'{lo:,}円' if lo == hi else f'{lo:,}円〜{hi:,}円'
            if f"空室{proof['vacancy_count']}件" not in text or '賃料' + rent not in text:
                raise ValueError('production_detail_rental_terms_mismatch')
        verified.append(url)
    return verified


def verify_site(expected: dict, attempts: int = 10, interval: int = 15):
    for attempt in range(attempts):
        try:
            actual = get_json("cloud_release.json", expected["run_id"])
            if actual["run_id"] != expected["run_id"] or actual["public_sha256"] != expected["public_sha256"]:
                raise ValueError("production_release_marker_not_updated")
            rows = get_json("data/buildings.json", expected["run_id"])
            compare(expected, rows)
            verify_detail_pages(expected, rows)
            return rows
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
