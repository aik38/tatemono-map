from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class BuildingRow:
    building_id: str
    canonical_name: str
    canonical_address: str
    norm_name: str
    norm_address: str
    created_at: str
    updated_at: str
    listings_cnt: int


def _normalize_name(value: str) -> str:
    return "".join((value or "").strip().lower().split())


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _load_buildings(conn: sqlite3.Connection) -> list[BuildingRow]:
    cols = _table_columns(conn, "buildings")
    name_col = "normalized_name" if "normalized_name" in cols else "norm_name"
    address_col = "normalized_address" if "normalized_address" in cols else "norm_address"
    listings = {
        row[0]: row[1]
        for row in conn.execute(
            """
            SELECT COALESCE(building_key, ''), COUNT(*)
            FROM listings
            WHERE COALESCE(building_key, '') <> ''
            GROUP BY building_key
            """
        ).fetchall()
    }
    rows = conn.execute(
        f"""
        SELECT
            building_id,
            COALESCE(canonical_name, ''),
            COALESCE(canonical_address, ''),
            COALESCE({name_col}, ''),
            COALESCE({address_col}, ''),
            COALESCE(created_at, ''),
            COALESCE(updated_at, '')
        FROM buildings
        """
    ).fetchall()
    return [
        BuildingRow(
            building_id=row[0],
            canonical_name=row[1],
            canonical_address=row[2],
            norm_name=row[3],
            norm_address=row[4],
            created_at=row[5],
            updated_at=row[6],
            listings_cnt=int(listings.get(row[0], 0) or 0),
        )
        for row in rows
    ]


def _build_components(rows: list[BuildingRow]) -> list[list[BuildingRow]]:
    id_to_row = {row.building_id: row for row in rows}
    parent = {row.building_id: row.building_id for row in rows}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    groups_norm: dict[tuple[str, str], list[str]] = defaultdict(list)
    groups_addr: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row.norm_name and row.norm_address:
            groups_norm[(row.norm_name, row.norm_address)].append(row.building_id)
        if row.canonical_address:
            groups_addr[row.canonical_address].append(row.building_id)

    for group in list(groups_norm.values()) + list(groups_addr.values()):
        if len(group) < 2:
            continue
        first = group[0]
        for other in group[1:]:
            union(first, other)

    components: dict[str, list[BuildingRow]] = defaultdict(list)
    for bid, row in id_to_row.items():
        root = find(bid)
        components[root].append(row)

    return [sorted(component, key=lambda r: r.building_id) for component in components.values() if len(component) > 1]


def _choose_keep(a: BuildingRow, b: BuildingRow) -> tuple[BuildingRow, BuildingRow]:
    if a.listings_cnt > 0 and b.listings_cnt == 0:
        return a, b
    if b.listings_cnt > 0 and a.listings_cnt == 0:
        return b, a
    ordered = sorted(
        [a, b],
        key=lambda r: (
            r.created_at or "9999-99-99",
            r.updated_at or "9999-99-99",
            r.building_id,
        ),
    )
    return ordered[0], ordered[1]


def _evaluate_component(component: list[BuildingRow]) -> tuple[bool, str, BuildingRow | None, BuildingRow | None]:
    if len(component) != 2:
        return False, "group_size_gt_2", None, None

    a, b = component
    if (a.listings_cnt > 0 and b.listings_cnt == 0) or (b.listings_cnt > 0 and a.listings_cnt == 0):
        keep, drop = _choose_keep(a, b)
        return True, "listings_prefer_nonzero", keep, drop

    if a.listings_cnt == 0 and b.listings_cnt == 0:
        if (
            a.canonical_address
            and a.canonical_address == b.canonical_address
            and _normalize_name(a.canonical_name) == _normalize_name(b.canonical_name)
        ):
            keep, drop = _choose_keep(a, b)
            return True, "both_zero_identical_canonical", keep, drop

    return False, "ambiguous_conflict", None, None


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run(db_path: Path, review_dir: Path) -> int:
    review_dir.mkdir(parents=True, exist_ok=True)
    suffix = _timestamp()
    merge_csv = review_dir / f"duplicate_merge_{suffix}.csv"
    candidate_csv = review_dir / f"duplicate_candidates_{suffix}.csv"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = _load_buildings(conn)
        components = _build_components(rows)

        merge_rows: list[dict[str, object]] = []
        candidate_rows: list[dict[str, object]] = []
        planned_merges: list[tuple[BuildingRow, BuildingRow, str]] = []

        for component in components:
            safe, reason, keep, drop = _evaluate_component(component)
            ids = ",".join(r.building_id for r in component)
            if safe and keep and drop:
                planned_merges.append((keep, drop, reason))
                merge_rows.append(
                    {
                        "keep_id": keep.building_id,
                        "drop_id": drop.building_id,
                        "reason": reason,
                        "listings_cnt_keep": keep.listings_cnt,
                        "listings_cnt_drop": drop.listings_cnt,
                        "applied": 0,
                    }
                )
            else:
                candidate_rows.append(
                    {
                        "building_ids": ids,
                        "reason": reason,
                        "listings_cnts": ",".join(f"{r.building_id}:{r.listings_cnt}" for r in component),
                        "canonical_addresses": ",".join(sorted({r.canonical_address for r in component if r.canonical_address})),
                    }
                )

        if candidate_rows:
            _write_csv(
                merge_csv,
                ["keep_id", "drop_id", "reason", "listings_cnt_keep", "listings_cnt_drop", "applied"],
                merge_rows,
            )
            _write_csv(
                candidate_csv,
                ["building_ids", "reason", "listings_cnts", "canonical_addresses"],
                candidate_rows,
            )
            print(f"[merge] duplicate_candidates_csv={candidate_csv}")
            print(f"[merge] duplicate_candidates_count={len(candidate_rows)}")
            print(f"[merge] duplicate_merge_csv={merge_csv}")
            print("[merge] RESULT=NOOP_AMBIGUOUS")
            return 0

        has_summary = _table_exists(conn, "building_summaries") and "building_key" in _table_columns(conn, "building_summaries")
        has_aliases = _table_exists(conn, "building_key_aliases")

        with conn:
            for keep, drop, reason in planned_merges:
                conn.execute(
                    "UPDATE listings SET building_key=? WHERE building_key=?",
                    (keep.building_id, drop.building_id),
                )
                if has_summary:
                    conn.execute(
                        "UPDATE building_summaries SET building_key=? WHERE building_key=?",
                        (keep.building_id, drop.building_id),
                    )
                if has_aliases:
                    conn.execute(
                        """
                        INSERT INTO building_key_aliases(alias_key, canonical_key, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(alias_key) DO UPDATE SET
                            canonical_key=excluded.canonical_key,
                            updated_at=CURRENT_TIMESTAMP
                        """,
                        (drop.building_id, keep.building_id),
                    )
                conn.execute("DELETE FROM buildings WHERE building_id=?", (drop.building_id,))

        applied_rows = [dict(row, applied=1) for row in merge_rows]
        _write_csv(
            merge_csv,
            ["keep_id", "drop_id", "reason", "listings_cnt_keep", "listings_cnt_drop", "applied"],
            applied_rows,
        )
        print(f"[merge] duplicate_merge_csv={merge_csv}")
        print(f"[merge] merged_count={len(planned_merges)}")
        print("[merge] RESULT=MERGED")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely merge duplicate buildings.")
    parser.add_argument("--db", type=Path, default=Path("data/tatemono_map.sqlite3"))
    parser.add_argument("--review-dir", type=Path, default=Path("tmp/review"))
    args = parser.parse_args()
    return run(args.db, args.review_dir)


if __name__ == "__main__":
    raise SystemExit(main())
