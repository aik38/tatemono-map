"""Read-only evidence report for published rent-null rows and duplicate candidates.

Usage: python scripts/audit_public_quality.py --public-json dist/data/buildings.json
Optional: --master verified-private-master.sqlite3 --out private-report.json
Never mutates SQLite, fixes amounts, or merges building IDs.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

AREA_AS_LAYOUT = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:m2|m²|㎡)\s*$", re.I)
FOCUS_NAMES = (
    "the STAGE 中原", "ビーライン足原", "ギャラン二島",
    "D-room Kasumi", "グローリア・ヒデ A", "ギャラクシー西小倉",
    "エヴァーグリーンN",
)


def _name_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s\u3000･・.．,，\-－ー]", "", text)


def public_audit(rows: list[dict]) -> dict:
    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_public_building_id")
    missing = [row for row in rows if (row.get("vacancy_count") or 0) > 0 and row.get("rent_min") is None]
    def is_area_layout(row):
        types = row.get("room_types") or []
        return bool(types) and all(isinstance(v, str) and AREA_AS_LAYOUT.fullmatch(v) for v in types)
    focus = []
    by_name = defaultdict(list)
    for row in rows:
        by_name[_name_key(row.get("name"))].append(row)
    for name in FOCUS_NAMES:
        matches = by_name.get(_name_key(name), [])
        focus.append({"name": name, "ids": [r["id"] for r in matches],
                      "rows": [{"id": r["id"], "name": r.get("name"), "address": r.get("address"),
                                "vacancy_count": r.get("vacancy_count"), "rent_min": r.get("rent_min"),
                                "area_min": r.get("area_min"), "room_types": r.get("room_types")}
                               for r in matches]})
    return {
        "totals": {"buildings": len(rows), "vacancies": sum(r.get("vacancy_count") or 0 for r in rows),
                   "rent_missing_buildings": len(missing),
                   "rent_missing_vacancies": sum(r.get("vacancy_count") or 0 for r in missing),
                   "rent_and_area_missing_buildings": sum(r.get("area_min") is None for r in missing),
                   "area_text_in_layout_buildings": sum(is_area_layout(r) for r in missing)},
        "rent_missing_dates": dict(sorted(Counter(r.get("updated_at") or "" for r in missing).items())),
        "rent_missing_rows": [
            {"id": r["id"], "name": r.get("name"), "address": r.get("address"),
             "vacancy_count": r.get("vacancy_count"), "updated_at": r.get("updated_at"),
             "room_types": r.get("room_types"), "area_text_in_layout": bool(is_area_layout(r))}
            for r in missing],
        "focus_pairs": focus,
    }


def master_audit(db_path: Path, public_result: dict) -> dict:
    """Inspect private evidence; never assume an older listing remains current."""
    from tatemono_map.normalize.effective_rentals import canonical_key, effective_rentals

    targets = {r["id"] for r in public_result["rent_missing_rows"]}
    targets.update(bid for p in public_result["focus_pairs"] for bid in p["ids"])
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        aliases = dict(conn.execute("SELECT alias_key,canonical_key FROM building_key_aliases"))
        related = targets | {alias for alias in aliases if canonical_key(alias, aliases) in targets}
        selected = [dict(r) for r in effective_rentals(conn)
                    if r["building_key"] in targets]
        selected_ids = {r["id"] for r in selected}
        placeholders = ",".join("?" for _ in related)
        all_rows = [dict(r) for r in conn.execute(
            "SELECT id, listing_key, building_key, name, address, room_label, rent_yen, maint_yen, "
            "layout, area_sqm, deposit_text, key_money_text, source_kind, source_url, "
            "ingest_run_id, updated_at, fetched_at FROM listings WHERE building_key IN (" + placeholders + ")",
            sorted(related))] if related else []
        for row in all_rows:
            row["selected_effective"] = row["id"] in selected_ids
            row["resolved_building_key"] = canonical_key(row["building_key"], aliases)
            row["area_text_in_layout"] = bool(AREA_AS_LAYOUT.fullmatch(row.get("layout") or ""))
        sources = [dict(r) for r in conn.execute(
            "SELECT source,evidence_id,building_id,raw_name,raw_address,extracted_at "
            "FROM building_sources WHERE building_id IN (" + placeholders + ")", sorted(related))] if related else []
        snapshots = [dict(r) for r in conn.execute("SELECT * FROM current_ingest_snapshots")]
        ranks = [dict(r) for r in conn.execute("SELECT * FROM source_priority WHERE domain='rental'")]
        summary = [dict(r) for r in conn.execute(
            "SELECT building_key,vacancy_count,rent_yen_min,rent_yen_max,area_sqm_min,area_sqm_max "
            "FROM building_summaries WHERE building_key IN (" + placeholders + ")", sorted(related))] if related else []
    by_target = defaultdict(list)
    for row in all_rows:
        by_target[row["resolved_building_key"]].append(row)
    diagnoses = []
    for target in public_result["rent_missing_rows"]:
        rs = by_target[target["id"]]
        active = [r for r in rs if r["selected_effective"]]
        other = [r for r in rs if not r["selected_effective"]]
        diagnoses.append({"id": target["id"], "selected_rows": len(active),
                          "selected_null_rent": sum(r["rent_yen"] is None for r in active),
                          "selected_area_as_layout": sum(r["area_text_in_layout"] for r in active),
                          "other_historical_or_unselected_rows_with_rent": sum(r["rent_yen"] is not None for r in other),
                          "requires_private_source_verification": True})
    return {"target_count": len(targets), "selected_count": len(selected),
            "listings": all_rows, "building_sources": sources, "current_ingest_snapshots": snapshots,
            "rental_source_priority": ranks, "building_summaries": summary, "diagnoses": diagnoses}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--public-json", required=True, type=Path)
    p.add_argument("--release-json", type=Path)
    p.add_argument("--master", type=Path, help="Verified GCS SQLite snapshot, opened read-only")
    p.add_argument("--out", type=Path, help="Private JSON report; never commit master evidence")
    args = p.parse_args(argv)
    rows = json.loads(args.public_json.read_text(encoding="utf-8"))
    report = {"public": public_audit(rows)}
    if args.release_json:
        release = json.loads(args.release_json.read_text(encoding="utf-8"))
        if release.get("rendered_buildings") != len(rows):
            raise ValueError("release_public_json_count_mismatch")
        report["release"] = {k: release.get(k) for k in ("run_id", "source_commit", "rendered_buildings", "counts")}
    if args.master:
        report["private_master"] = master_audit(args.master, report["public"])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"release": report.get("release"), "public_totals": report["public"]["totals"],
                      "private_diagnoses": len(report.get("private_master", {}).get("diagnoses", [])),
                      "out": str(args.out) if args.out else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
