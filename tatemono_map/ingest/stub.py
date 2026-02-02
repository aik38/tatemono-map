# tatemono_map/ingest/stub.py
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    # Webに出す前提の last_updated はUTCのISOで統一（表示側で整形すればOK）
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cur.fetchall()}  # row[1] = name
    return cols


def _ensure_parent_dir(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _normalize_vacancy_status(value: str | None) -> str:
    if value is None or value.strip() == "":
        return "満室"
    if value not in {"満室", "空室あり"}:
        raise ValueError("vacancy_status must be '満室' or '空室あり'")
    return value


def ingest_stub(
    db_path: Path, building_key: str, fail: bool = False, vacancy_status: str | None = None
) -> None:
    if fail:
        raise RuntimeError("Intentional ingest failure (stub)")

    _ensure_parent_dir(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        # 失敗時にDBを汚さない：1トランザクションで完結
        conn.execute("BEGIN IMMEDIATE")

        cols = _table_columns(conn, "building_summaries")
        now = _utc_iso()

        # まずは「demo（seed）」を更新する方針にして、NOT NULL制約に踏みにくくする
        cur = conn.execute(
            "SELECT 1 FROM building_summaries WHERE building_key = ? LIMIT 1",
            (building_key,),
        )
        exists = cur.fetchone() is not None

        # 更新候補（存在するカラムだけ更新）
        normalized_vacancy_status = _normalize_vacancy_status(vacancy_status)
        candidates: dict[str, Any] = {
            "last_updated": now,
            "updated_at": now,
            # “DB更新が起きた”ことを見分けやすくするための任意フィールド（存在するなら更新）
            "source": "stub",
            "vacancy_status": normalized_vacancy_status,
        }
        update_map = {k: v for k, v in candidates.items() if k in cols}

        if exists:
            if not update_map:
                # last_updated が無いなどは仕様違反なので明示的に落とす
                raise RuntimeError("No updatable columns found on building_summaries (expected last_updated).")

            set_clause = ", ".join([f"{k} = ?" for k in update_map.keys()])
            params = list(update_map.values()) + [building_key]
            conn.execute(
                f"UPDATE building_summaries SET {set_clause} WHERE building_key = ?",
                params,
            )
        else:
            # 0件でも seed が入る想定だが、万一0件でも upsert できるように最低限insert
            insert_map: dict[str, Any] = {"building_key": building_key, **update_map}
            if "building_key" not in cols:
                raise RuntimeError("building_summaries.building_key not found (schema unexpected).")
            if "last_updated" not in cols:
                raise RuntimeError("building_summaries.last_updated not found (spec requires it).")

            columns = ", ".join(insert_map.keys())
            placeholders = ", ".join(["?"] * len(insert_map))
            conn.execute(
                f"INSERT INTO building_summaries ({columns}) VALUES ({placeholders})",
                list(insert_map.values()),
            )

        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Path to SQLite DB (SQLITE_DB_PATH)")
    ap.add_argument("--building-key", default="demo", help="Target building_key to upsert (default: demo)")
    ap.add_argument(
        "--vacancy-status",
        default="満室",
        help="vacancy_status to upsert (default: 満室, allowed: 満室/空室あり)",
    )
    ap.add_argument("--fail", action="store_true", help="Intentionally fail to test failure path")
    args = ap.parse_args()

    ingest_stub(
        Path(args.db),
        building_key=args.building_key,
        fail=args.fail,
        vacancy_status=args.vacancy_status,
    )


if __name__ == "__main__":
    main()
