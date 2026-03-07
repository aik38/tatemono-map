from __future__ import annotations

import argparse
import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from tatemono_map.building_registry.normalization import normalize_building_input


@dataclass
class CorrectionRow:
    row_no: int
    status: str
    action: str
    target_building_name: str
    target_address: str
    field: str
    old_value: str
    new_value: str
    note: str
    source: str
    error_type: str


@dataclass
class ProcessResult:
    row_no: int
    status: str
    matched_building_id: str
    before_value: str
    after_value: str
    outcome: str
    reason: str


def _clean(value: str | None) -> str:
    return (value or "").strip()


def load_rows(csv_path: Path) -> list[CorrectionRow]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows: list[CorrectionRow] = []
        for i, row in enumerate(reader, start=2):
            rows.append(
                CorrectionRow(
                    row_no=i,
                    status=_clean(row.get("status")),
                    action=_clean(row.get("action")),
                    target_building_name=_clean(row.get("target_building_name")),
                    target_address=_clean(row.get("target_address")),
                    field=_clean(row.get("field")),
                    old_value=_clean(row.get("old_value")),
                    new_value=_clean(row.get("new_value")),
                    note=_clean(row.get("note")),
                    source=_clean(row.get("source")),
                    error_type=_clean(row.get("error_type")),
                )
            )
    return rows


def _find_candidates(conn: sqlite3.Connection, row: CorrectionRow) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[str] = []

    if row.target_building_name:
        clauses.append("canonical_name = ?")
        params.append(row.target_building_name)
    if row.target_address:
        clauses.append("canonical_address = ?")
        params.append(row.target_address)

    where_clause = " AND ".join(clauses) if clauses else "1=1"
    sql = f"""
        SELECT building_id, canonical_name, canonical_address, norm_name, norm_address
          FROM buildings
         WHERE {where_clause}
         ORDER BY building_id
    """
    results = conn.execute(sql, params).fetchall()

    if results:
        return results

    fallback_sql = """
        SELECT building_id, canonical_name, canonical_address, norm_name, norm_address
          FROM buildings
         WHERE canonical_name = ?
            OR canonical_address = ?
            OR canonical_name = ?
            OR canonical_address = ?
         ORDER BY building_id
    """
    return conn.execute(
        fallback_sql,
        (row.target_building_name, row.target_address, row.old_value, row.old_value),
    ).fetchall()


def _should_hold(row: CorrectionRow, allow_incomplete_address: bool) -> str | None:
    if row.action not in {"fix", "drop_duplicate_loser"}:
        return f"unsupported_action:{row.action or 'empty'}"
    if row.status not in {"pending", "approved", "applied"}:
        return f"unsupported_status:{row.status or 'empty'}"

    if row.action == "drop_duplicate_loser":
        return None

    if row.field not in {"building_name", "address"}:
        return f"unsupported_field:{row.field or 'empty'}"
    if not row.new_value:
        return "missing_new_value"
    if (
        row.target_building_name == "CITRUS TREE"
        and row.field == "address"
        and row.error_type == "address_incomplete"
        and ("枝番未確認" in row.note or "未確認" in row.note)
        and not allow_incomplete_address
    ):
        return "hold_citrus_tree_incomplete_address"
    return None


def _value_for_field(row_obj: sqlite3.Row, field: str) -> str:
    return row_obj["canonical_name"] if field == "building_name" else row_obj["canonical_address"]


def _duplicate_candidates(conn: sqlite3.Connection, building_id: str, norm_name: str, norm_address: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT building_id, canonical_name, canonical_address
          FROM buildings
         WHERE building_id <> ?
           AND (
                (? <> '' AND norm_name = ?)
             OR (? <> '' AND norm_address = ?)
           )
         ORDER BY building_id
        """,
        (building_id, norm_name, norm_name, norm_address, norm_address),
    ).fetchall()


def process_rows(
    conn: sqlite3.Connection,
    rows: Iterable[CorrectionRow],
    *,
    apply: bool,
    allow_incomplete_address: bool,
) -> tuple[list[ProcessResult], list[dict[str, str]]]:
    results: list[ProcessResult] = []
    duplicates: list[dict[str, str]] = []

    for row in rows:
        hold_reason = _should_hold(row, allow_incomplete_address)
        if hold_reason:
            results.append(
                ProcessResult(
                    row_no=row.row_no,
                    status=row.status,
                    matched_building_id="",
                    before_value="",
                    after_value="",
                    outcome="held",
                    reason=hold_reason,
                )
            )
            continue

        candidates = _find_candidates(conn, row)
        if len(candidates) != 1:
            reason = "not_found" if len(candidates) == 0 else f"ambiguous:{len(candidates)}"
            results.append(
                ProcessResult(
                    row_no=row.row_no,
                    status=row.status,
                    matched_building_id="",
                    before_value="",
                    after_value="",
                    outcome="held",
                    reason=reason,
                )
            )
            continue

        building = candidates[0]

        if row.action == "drop_duplicate_loser":
            if apply:
                conn.execute(
                    """
                    UPDATE buildings
                       SET hidden_from_public = 1,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE building_id = ?
                    """,
                    (building["building_id"],),
                )
            results.append(
                ProcessResult(
                    row_no=row.row_no,
                    status=row.status,
                    matched_building_id=building["building_id"],
                    before_value="0",
                    after_value="1",
                    outcome="applied" if apply else "dry_run",
                    reason="hidden_from_public",
                )
            )
            continue

        before_value = _value_for_field(building, row.field)
        if row.old_value and before_value != row.old_value:
            results.append(
                ProcessResult(
                    row_no=row.row_no,
                    status=row.status,
                    matched_building_id=building["building_id"],
                    before_value=before_value,
                    after_value=row.new_value,
                    outcome="held",
                    reason="old_value_mismatch",
                )
            )
            continue

        new_name = building["canonical_name"]
        new_address = building["canonical_address"]
        if row.field == "building_name":
            new_name = row.new_value
        else:
            new_address = row.new_value
        normalized = normalize_building_input(new_name, new_address)

        if apply:
            conn.execute(
                """
                UPDATE buildings
                   SET canonical_name = ?,
                       canonical_address = ?,
                       norm_name = ?,
                       norm_address = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE building_id = ?
                """,
                (
                    normalized.raw_name,
                    normalized.canonical_address,
                    normalized.normalized_name,
                    normalized.normalized_address,
                    building["building_id"],
                ),
            )

        results.append(
            ProcessResult(
                row_no=row.row_no,
                status=row.status,
                matched_building_id=building["building_id"],
                before_value=before_value,
                after_value=row.new_value,
                outcome="applied" if apply else "dry_run",
                reason="ok",
            )
        )

        for dup in _duplicate_candidates(
            conn,
            building["building_id"],
            normalized.normalized_name,
            normalized.normalized_address,
        ):
            duplicates.append(
                {
                    "row_no": str(row.row_no),
                    "building_id": building["building_id"],
                    "building_name": normalized.raw_name,
                    "building_address": normalized.canonical_address,
                    "duplicate_building_id": dup["building_id"],
                    "duplicate_name": dup["canonical_name"] or "",
                    "duplicate_address": dup["canonical_address"] or "",
                }
            )

    return results, duplicates


def write_csv(path: Path, rows: Iterable[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely apply manual building corrections")
    parser.add_argument("--db", default="data/tatemono_map.sqlite3")
    parser.add_argument("--corrections", default="tmp/manual/building_corrections.csv")
    parser.add_argument("--apply", action="store_true", help="Actually update the DB")
    parser.add_argument(
        "--allow-incomplete-address",
        action="store_true",
        help="Allow applying address_incomplete rows such as CITRUS TREE when note says unresolved branch number",
    )
    parser.add_argument("--output-dir", default="tmp/manual/outputs")
    args = parser.parse_args()

    db_path = Path(args.db)
    csv_path = Path(args.corrections)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    if not csv_path.exists():
        raise SystemExit(f"Corrections CSV not found: {csv_path}")

    rows = load_rows(csv_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    results, duplicates = process_rows(
        conn,
        rows,
        apply=args.apply,
        allow_incomplete_address=args.allow_incomplete_address,
    )

    if args.apply:
        conn.commit()
    conn.close()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    results_path = output_dir / f"building_corrections_report_{stamp}.csv"
    duplicates_path = output_dir / f"building_corrections_duplicates_{stamp}.csv"

    write_csv(
        results_path,
        (
            {
                "row_no": str(r.row_no),
                "status": r.status,
                "matched_building_id": r.matched_building_id,
                "before_value": r.before_value,
                "after_value": r.after_value,
                "outcome": r.outcome,
                "reason": r.reason,
            }
            for r in results
        ),
        ["row_no", "status", "matched_building_id", "before_value", "after_value", "outcome", "reason"],
    )

    write_csv(
        duplicates_path,
        duplicates,
        [
            "row_no",
            "building_id",
            "building_name",
            "building_address",
            "duplicate_building_id",
            "duplicate_name",
            "duplicate_address",
        ],
    )

    print(f"rows={len(rows)} apply={args.apply} results={results_path} duplicates={duplicates_path}")


if __name__ == "__main__":
    main()
