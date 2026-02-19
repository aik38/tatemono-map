from __future__ import annotations

import argparse
import csv
from pathlib import Path

from tatemono_map.buildings_master.from_sources import (
    _stable_key,
    normalize_address_jp,
    normalize_building_name,
)


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV header missing: {path}")
        return [{k: (v or "") for k, v in row.items()} for row in reader]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _row_building_key(row: dict[str, str]) -> str:
    candidate = (row.get("building_key") or "").strip()
    if candidate:
        return candidate
    return _stable_key(
        normalize_address_jp((row.get("address") or "").strip()),
        normalize_building_name((row.get("building_name") or "").strip()),
    )


def run(input_csv: Path, overrides_csv: Path, alias_csv: Path) -> tuple[int, int]:
    rows = _load_csv(input_csv)

    by_evidence: dict[str, list[dict[str, str]]] = {}
    by_key: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        evidence = (row.get("evidence_url_or_id") or "").strip()
        if evidence:
            by_evidence.setdefault(evidence, []).append(row)
        bkey = _row_building_key(row)
        if bkey:
            by_key.setdefault(bkey, []).append(row)

    unresolved: list[dict[str, str]] = []
    override_rows: list[dict[str, str]] = []
    alias_rows: list[dict[str, str]] = []

    for row in rows:
        merge_to = (row.get("merge_to_evidence") or "").strip()
        if not merge_to:
            continue

        winners = by_evidence.get(merge_to)
        winner_ref = merge_to
        if not winners:
            winners = by_key.get(merge_to)
            winner_ref = merge_to

        if not winners:
            unresolved.append(row)
            continue
        if len(winners) > 1:
            raise ValueError(f"Ambiguous winner for merge_to_evidence={merge_to}: {len(winners)} rows")

        winner = winners[0]
        winner_name = (winner.get("building_name") or "").strip()
        winner_addr = (winner.get("address") or "").strip()
        winner_source = (winner.get("source") or "").strip()
        winner_evidence = (winner.get("evidence_url_or_id") or "").strip()
        winner_key = _row_building_key(winner)
        winner_display = winner_evidence or winner_key or winner_ref

        loser_source = (row.get("source") or "").strip()
        loser_evidence = (row.get("evidence_url_or_id") or "").strip()
        loser_key = _row_building_key(row)

        override_rows.append(
            {
                "source": loser_source,
                "evidence_url_or_id": loser_evidence,
                "building_key": "" if loser_evidence else loser_key,
                "building_name_override": winner_name,
                "address_override": winner_addr,
                "ignore_flag": "",
                "note": f"merged to {winner_source} {winner_display}",
            }
        )

        alias_rows.append(
            {
                "old_building_key": loser_key,
                "new_building_key": _stable_key(
                    normalize_address_jp(winner_addr),
                    normalize_building_name(winner_name),
                ),
                "note": f"merged to {winner_source} {winner_display}",
            }
        )

    if unresolved:
        print("ERROR: unresolved merge_to_evidence rows:")
        for row in unresolved:
            print(
                " | ".join(
                    [
                        (row.get("source") or "").strip(),
                        (row.get("building_name") or "").strip(),
                        (row.get("address") or "").strip(),
                        (row.get("building_key") or "").strip(),
                        (row.get("evidence_url_or_id") or "").strip(),
                        (row.get("merge_to_evidence") or "").strip(),
                    ]
                )
            )
        raise SystemExit(1)

    _write_csv(
        overrides_csv,
        [
            "source",
            "evidence_url_or_id",
            "building_key",
            "building_name_override",
            "address_override",
            "ignore_flag",
            "note",
        ],
        override_rows,
    )
    _write_csv(alias_csv, ["old_building_key", "new_building_key", "note"], alias_rows)
    return len(override_rows), len(alias_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate overrides and building_key aliases from UI edited CSV")
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--overrides-csv", required=True)
    parser.add_argument("--alias-csv", required=True)
    args = parser.parse_args()
    n_overrides, n_aliases = run(
        input_csv=Path(args.input_csv),
        overrides_csv=Path(args.overrides_csv),
        alias_csv=Path(args.alias_csv),
    )
    print(f"generated overrides={n_overrides} aliases={n_aliases}")


if __name__ == "__main__":
    main()
