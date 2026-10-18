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
        ids, aliases = publication_ids(path)
        if len(ids) != counts['buildings']:
            raise ValueError('hidden_building_in_public_database')
        for table in ('building_summaries', 'building_rental_summaries', 'building_sale_summaries'):
            if table in tables and any(r[0] not in ids for r in conn.execute(f'SELECT building_key FROM {table}')):
                raise ValueError('orphan_public_summary')
        if 'building_key_aliases' in tables:
            if any(r[0] not in aliases or r[1] not in ids | aliases
                   for r in conn.execute('SELECT alias_key,canonical_key FROM building_key_aliases')):
                raise ValueError('private_or_dangling_public_alias')
        return {**counts, "vacancies": conn.execute("SELECT COALESCE(SUM(vacancy_count),0) FROM building_summaries").fetchone()[0]}


def publication_ids(database: Path) -> tuple[set[str], set[str]]:
    """Visible canonical rows in the adopted master define publication.

    A previous public artifact is used only to guard against accidental loss.
    Explicitly hidden buildings and aliases resolving to them stay private.
    """
    with readonly(database) as conn:
        ids = {r[0] for r in conn.execute('SELECT building_id FROM buildings WHERE COALESCE(hidden_from_public,0)=0')}
        has_aliases = conn.execute("SELECT 1 FROM sqlite_master WHERE name='building_key_aliases'").fetchone()
        mapping = dict(conn.execute('SELECT alias_key,canonical_key FROM building_key_aliases')) if has_aliases else {}
        hidden = {r[0] for r in conn.execute('SELECT building_id FROM buildings WHERE COALESCE(hidden_from_public,0)<>0')}
        aliases=set()
        for key in mapping:
            target=key
            seen=set()
            while target in mapping and mapping[target]!=target:
                if target in hidden:
                    break
                if target in seen:
                    raise ValueError('publication_baseline_alias_cycle')
                seen.add(target)
                target=mapping[target]
            if target in ids and key not in hidden:
                aliases.add(key)
    return ids, aliases


def export_public(master: Path, output: Path, *, baseline: Path | None = None) -> dict:
    if master.resolve() == output.resolve():
        raise ValueError("master_and_public_paths_must_differ")
    allowed, allowed_aliases = publication_ids(master)
    previous, _ = publication_ids(baseline) if baseline is not None else (set(), set())
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    # Copy precisely the same required/optional tables as publish_public.ps1.
    # Never back up the whole master into a public file (deleted pages can leak).
    with readonly(master) as src, closing(sqlite3.connect(temporary)) as dst:
        current = {r[0] for r in src.execute('SELECT building_id FROM buildings')}
        # A hidden row is an explicit exclusion; a removed row needs a recorded
        # canonical alias whose endpoint remains public. Never lose old URLs
        # merely because a source has no offers this week.
        if not previous <= current | allowed_aliases:
            raise ValueError('existing_public_building_missing_from_master')
        for table in REQUIRED + OPTIONAL:
            row = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if row is None:
                if table in REQUIRED:
                    raise ValueError("public_required_table_missing")
                continue
            dst.execute(row[0])
            columns = len(src.execute(f'SELECT * FROM "{table}" LIMIT 0').description)
            cursor = src.execute(f'SELECT * FROM "{table}"')
            names = [column[0] for column in cursor.description]
            rows = cursor
            field = 'building_id' if table == 'buildings' else 'canonical_key' if table == 'building_key_aliases' else 'building_key'
            key_index = names.index(field)
            alias_index = names.index('alias_key') if table == 'building_key_aliases' else None
            targets = allowed | allowed_aliases if alias_index is not None else allowed
            rows = (r for r in cursor if r[key_index] in targets and (alias_index is None or r[alias_index] in allowed_aliases))
            dst.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in range(columns))})', rows)
        dst.commit()
    counts = validate_public(temporary)
    os.replace(temporary, output)
    return counts


def rendered_ids(database: Path) -> set[str]:
    """Only explicit canonical aliases can reduce the search/page ID set."""
    from tatemono_map.normalize.effective_rentals import canonical_key
    ids, _ = publication_ids(database)
    with readonly(database) as conn:
        present = conn.execute("SELECT 1 FROM sqlite_master WHERE name='building_key_aliases'").fetchone()
        mapping = dict(conn.execute('SELECT alias_key,canonical_key FROM building_key_aliases')) if present else {}
    return {target if (target := canonical_key(key, mapping)) in ids else key for key in ids}


def id_fingerprint(ids) -> str:
    return hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()
