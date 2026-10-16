"""Portable version of the publish_public.ps1 table-copy contract."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

REQUIRED = ("buildings", "building_summaries")
OPTIONAL = ("building_key_aliases", "building_rental_summaries", "building_sale_summaries")
PUBLIC_TABLES = frozenset(REQUIRED + OPTIONAL)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def readonly(path: Path):
    if not path.is_file():
        raise ValueError("database_missing")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        yield conn


def snapshot_sqlite(source: Path, output: Path) -> None:
    """Include committed WAL pages in the single standalone uploaded file."""
    if source.resolve() == output.resolve():
        raise ValueError("snapshot_paths_must_differ")
    output.unlink(missing_ok=True)
    with readonly(source) as src, closing(sqlite3.connect(output)) as dst:
        src.backup(dst)
        dst.commit()
        dst.execute("PRAGMA journal_mode=DELETE").fetchone()
        if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("snapshot_integrity_failed")


def validate_public(path: Path) -> dict:
    with readonly(path) as conn:
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("public_integrity_failed")
        objects = conn.execute("SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if any(kind != "table" or name not in PUBLIC_TABLES for name, kind in objects):
            raise ValueError("unexpected_public_database_object")
        tables = {name for name, _ in objects}
        if not set(REQUIRED) <= tables:
            raise ValueError("public_required_table_missing")
        counts = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in REQUIRED}
        if min(counts.values()) <= 0:
            raise ValueError("public_database_empty")
        if conn.execute("SELECT COUNT(*) FROM building_summaries WHERE vacancy_count < 0").fetchone()[0]:
            raise ValueError("negative_vacancy_count")
        return {**counts, "vacancies": conn.execute("SELECT COALESCE(SUM(vacancy_count),0) FROM building_summaries").fetchone()[0]}


def export_public(master: Path, output: Path) -> dict:
    if master.resolve() == output.resolve():
        raise ValueError("master_and_public_paths_must_differ")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    # Copy precisely the same required/optional tables as publish_public.ps1.
    # Never back up the whole master into a public file (deleted pages can leak).
    with readonly(master) as src, closing(sqlite3.connect(temporary)) as dst:
        for table in REQUIRED + OPTIONAL:
            row = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if row is None:
                if table in REQUIRED:
                    raise ValueError("public_required_table_missing")
                continue
            dst.execute(row[0])
            columns = len(src.execute(f'SELECT * FROM "{table}" LIMIT 0').description)
            dst.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in range(columns))})', src.execute(f'SELECT * FROM "{table}"'))
        dst.commit()
    counts = validate_public(temporary)
    os.replace(temporary, output)
    return counts
