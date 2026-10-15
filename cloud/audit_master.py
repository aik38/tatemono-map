#!/usr/bin/env python3
"""Read-only candidate inventory. No public DB promotion or automatic selection."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from tatemono_map.cloud.public_db import readonly, sha256, snapshot_sqlite
from tatemono_map.cloud.pipeline import validate_master


def audit(path: Path, canonical_keys: set[str] | None = None, alias_keys: set[str] | None = None) -> dict:
    result = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path), "candidate": False}
    wal = Path(str(path) + "-wal")
    result["wal_present"] = wal.exists() and wal.stat().st_size > 0
    try:
        with readonly(path) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result["counts"] = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] if table in tables else None for table in ("buildings", "listings", "current_ingest_snapshots", "ingest_runs", "sale_listings", "raw_sources")}
            keys = {str(r[0]) for r in conn.execute("SELECT building_id FROM buildings")}
            result["canonical_id_fingerprint"] = hashlib.sha256("\n".join(sorted(keys)).encode()).hexdigest()
            result["foreign_key_errors"] = len(conn.execute("PRAGMA foreign_key_check").fetchall())
            if "listings" in tables:
                result["listing_counts_by_source"] = dict(conn.execute("SELECT source_kind, COUNT(*) FROM listings GROUP BY source_kind"))
            if canonical_keys is not None:
                result["provided_canonical_ids_present"] = len(keys & canonical_keys)
                result["provided_canonical_ids_missing"] = len(canonical_keys - keys)
            mapping = dict(conn.execute("SELECT alias_key,canonical_key FROM building_key_aliases")) if "building_key_aliases" in tables else {}
            def resolved(key):
                seen = set()
                while key not in keys and key in mapping and key not in seen:
                    seen.add(key)
                    key = mapping[key]
                return key in keys
            if canonical_keys is not None:
                result["provided_canonical_ids_unresolved_after_aliases"] = sum(not resolved(key) for key in canonical_keys)
            if alias_keys is not None:
                result["provided_alias_targets_unresolved"] = sum(not resolved(key) for key in alias_keys)
            if "current_ingest_snapshots" in tables and "ingest_runs" in tables:
                result["invalid_current_runs"] = conn.execute("SELECT COUNT(*) FROM current_ingest_snapshots c LEFT JOIN ingest_runs r ON r.id=c.ingest_run_id WHERE r.status IS NULL OR r.status!='completed'").fetchone()[0]
                result["latest_completed_run"] = conn.execute("SELECT MAX(finished_at) FROM ingest_runs WHERE status='completed'").fetchone()[0]
        validate_master(path)
        result["candidate"] = not result["wal_present"] and not result["foreign_key_errors"] and not result.get("invalid_current_runs") and not result.get("provided_canonical_ids_unresolved_after_aliases") and not result.get("provided_alias_targets_unresolved")
        result["decision"] = "requires_private_history_and_scope_review" if result["candidate"] else "identity_or_current_snapshot_mismatch"
        if result["wal_present"]:
            result["decision"] = "standalone_snapshot_required_wal_present"
        if sha256(path) != result["sha256"]:
            result["candidate"] = False
            result["decision"] = "source_changed_during_audit"
    except Exception:
        result["decision"] = "rejected_not_verified_master"
    return result


def read_keys(path: Path | None, column: str) -> set[str] | None:
    if path is None:
        return None
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row[column] for row in csv.DictReader(stream)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, action="append", default=[])
    parser.add_argument("--candidate", type=Path, action="append", default=[])
    parser.add_argument("--canonical-csv", type=Path)
    parser.add_argument("--aliases-csv", type=Path)
    parser.add_argument("--snapshot-dir", type=Path, help="optional private standalone copies, includes committed WAL; never changes source")
    parser.add_argument("--output", type=Path, default=Path("work/master-candidates.json"))
    args = parser.parse_args()
    paths = set(args.candidate)
    for root in args.root:
        if root.is_dir():
            paths.update(root.rglob("*.sqlite3"))
            paths.update(root.rglob("*.db"))
    canonical = read_keys(args.canonical_csv, "building_key")
    aliases = read_keys(args.aliases_csv, "canonical_building_key")
    reports = []
    for path in sorted(paths):
        if not path.is_file() or args.snapshot_dir and args.snapshot_dir.resolve() in path.resolve().parents:
            continue
        if args.snapshot_dir:
            import os
            args.snapshot_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(args.snapshot_dir, 0o700)
            target = args.snapshot_dir / (hashlib.sha256(str(path.resolve()).encode()).hexdigest() + ".sqlite3")
            # A WAL source needs a SQLite backup, not a bare filesystem copy.
            # Copy first, audit the immutable snapshot; never select by mtime.
            try:
                snapshot_sqlite(path, target)
                reports.append({"source_path": str(path), **audit(target, canonical, aliases)})
            except Exception:
                target.unlink(missing_ok=True)
                reports.append({"source_path": str(path), "candidate": False, "decision": "standalone_snapshot_failed"})
        else:
            reports.append(audit(path, canonical, aliases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"auto_selected": False, "candidates": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"files_checked": len(reports), "possible_masters": sum(r["candidate"] for r in reports), "auto_selected": False}))


if __name__ == "__main__":
    main()
