from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


BODY_COLUMN_CANDIDATES = ["content", "body", "html", "raw_html", "payload"]


def _resolve_db_path(db_arg: str | None) -> Path:
    if db_arg:
        return Path(db_arg).expanduser().resolve()
    env_path = os.getenv("SQLITE_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "data" / "tatemono_map.sqlite3"


def _get_table_columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, str, int]]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [(row[1], row[2], row[5]) for row in rows]


def _get_pk_column(conn: sqlite3.Connection, table: str) -> str | None:
    for name, _col_type, pk_flag in _get_table_columns(conn, table):
        if pk_flag == 1:
            return name
    return None


def _get_body_column(conn: sqlite3.Connection, table: str) -> str:
    columns = {name for name, _col_type, _pk in _get_table_columns(conn, table)}
    for candidate in BODY_COLUMN_CANDIDATES:
        if candidate in columns:
            return candidate
    raise RuntimeError(
        f"No body column found in {table}. Tried: {', '.join(BODY_COLUMN_CANDIDATES)}"
    )


def _print_stats(conn: sqlite3.Connection) -> None:
    print("raw_sources counts by source_system/source_kind:")
    rows = conn.execute(
        """
        SELECT source_system, source_kind, COUNT(*)
        FROM raw_sources
        GROUP BY source_system, source_kind
        ORDER BY source_system, source_kind
        """
    ).fetchall()
    for row in rows:
        print(f"  {row[0]} / {row[1]}: {row[2]}")
    listing_count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    building_count = conn.execute("SELECT COUNT(*) FROM building_summaries").fetchone()[0]
    print(f"listings total: {listing_count}")
    print(f"building_summaries total: {building_count}")


def _print_schema(conn: sqlite3.Connection, table: str) -> None:
    rows = _get_table_columns(conn, table)
    if not rows:
        print(f"No schema info for table: {table}")
        return
    print(f"Schema for {table}:")
    for name, col_type, pk_flag in rows:
        pk_marker = " PK" if pk_flag == 1 else ""
        print(f"  {name} ({col_type}){pk_marker}")


def _dump_latest_raw(
    conn: sqlite3.Connection,
    *,
    source_system: str,
    source_kind: str,
    output_path: Path,
) -> None:
    table = "raw_sources"
    pk_column = _get_pk_column(conn, table)
    body_column = _get_body_column(conn, table)

    order_column = pk_column or "rowid"
    query = f"""
        SELECT {body_column}
        FROM {table}
        WHERE source_system = ? AND source_kind = ?
        ORDER BY {order_column} DESC
        LIMIT 1
    """
    row = conn.execute(query, (source_system, source_kind)).fetchone()
    if row is None:
        raise RuntimeError("No matching raw_sources rows found.")
    payload = row[0]
    if payload is None:
        raise RuntimeError("Latest raw_sources row has no payload.")
    if isinstance(payload, memoryview):
        payload_bytes = payload.tobytes()
    elif isinstance(payload, bytes):
        payload_bytes = payload
    else:
        payload_bytes = str(payload).encode("utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload_bytes)
    print(f"Wrote {len(payload_bytes)} bytes to {output_path}")


def _maybe_open(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        print("--open is only supported on Windows.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect tatemono-map SQLite DB.")
    parser.add_argument("--db", default=None, help="Path to SQLite DB (SQLITE_DB_PATH)")
    parser.add_argument("--stats", action="store_true", help="Show table stats")
    parser.add_argument(
        "--schema",
        choices=["raw_sources", "listings", "building_summaries"],
        help="Print table schema",
    )
    parser.add_argument(
        "--dump-latest-raw",
        action="store_true",
        help="Dump latest raw_sources row matching --system/--kind",
    )
    parser.add_argument("--system", default=None, help="source_system for dump")
    parser.add_argument("--kind", default=None, help="source_kind for dump")
    parser.add_argument("--out", default=None, help="Output path for dump")
    parser.add_argument("--open", action="store_true", help="Open dump file (Windows)")
    args = parser.parse_args()

    if not (args.stats or args.schema or args.dump_latest_raw):
        parser.print_help()
        return

    db_path = _resolve_db_path(args.db)
    conn = sqlite3.connect(str(db_path))
    try:
        if args.stats:
            _print_stats(conn)
        if args.schema:
            _print_schema(conn, args.schema)
        if args.dump_latest_raw:
            if not (args.system and args.kind and args.out):
                raise RuntimeError(
                    "--dump-latest-raw requires --system, --kind, and --out"
                )
            output_path = Path(args.out).expanduser().resolve()
            _dump_latest_raw(
                conn,
                source_system=args.system,
                source_kind=args.kind,
                output_path=output_path,
            )
            if args.open:
                _maybe_open(output_path)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
