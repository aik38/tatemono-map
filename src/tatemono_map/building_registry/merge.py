"""Apply one evidence-confirmed merge, keeping every private source/history row."""
from __future__ import annotations
import json
import re
import unicodedata
from tatemono_map.building_registry.normalization import normalize_address_for_matching, normalize_ulucks_name
from tatemono_map.normalize.effective_rentals import canonical_key


def name_identity(name):
    return ''.join(normalize_ulucks_name(name or '').casefold().split())


def full_address(address):
    value = normalize_address_for_matching(address)
    return bool(re.search(r'\d+(?:-\d+){1,2}$', value)) and not any(x in value for x in ('、','〜'))


def same_identity(left, right):
    return bool(name_identity(left.canonical_name) and name_identity(left.canonical_name) == name_identity(right.canonical_name)
                and full_address(left.canonical_address) and full_address(right.canonical_address)
                and normalize_address_for_matching(left.canonical_address) == normalize_address_for_matching(right.canonical_address))


def merge_confirmed(conn, keep, drop, reason):
    if keep == drop: raise ValueError('merge_self')
    aliases = dict(conn.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
    # A nontrivial existing target must agree, never reverse another canonical decision.
    if canonical_key(keep, aliases) != keep: raise ValueError('merge_target_is_alias')
    old_target = canonical_key(drop, aliases)
    if old_target not in (drop,keep): raise ValueError('merge_conflicting_alias')
    before = conn.execute('SELECT * FROM buildings WHERE building_id=?',(drop,)).fetchone()
    if before is None or not conn.execute('SELECT 1 FROM buildings WHERE building_id=?',(keep,)).fetchone():
        raise ValueError('merge_building_missing')
    columns=[r[1] for r in conn.execute('PRAGMA table_info(buildings)')]
    conn.execute('CREATE TABLE IF NOT EXISTS quality_building_merges (old_id TEXT PRIMARY KEY,canonical_id TEXT NOT NULL,reason TEXT NOT NULL,old_row_json TEXT NOT NULL,merged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    conn.execute('INSERT INTO quality_building_merges(old_id,canonical_id,reason,old_row_json) VALUES (?,?,?,?)',
                 (drop,keep,reason,json.dumps(dict(zip(columns,before)),ensure_ascii=False)))
    # Aggregates are derived and rebuilt, never UPDATE into another summary PK.
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ('building_summaries','building_rental_summaries','building_sale_summaries'):
        if table in tables:conn.execute(f'DELETE FROM {table} WHERE building_key IN (?,?)',(drop,keep))
    refs={'listings':'building_key','raw_units':'building_key','sale_listings':'building_key',
          'building_sources':'building_id','cloud_collection_rows':'building_id','cloud_review_decisions':'building_id'}
    for table,column in refs.items():
        if table in tables:conn.execute(f'UPDATE {table} SET {column}=? WHERE {column}=?',(keep,drop))
    # Preserve nonempty facts without overwriting the surviving identity or terms.
    for column in ('structure','built_year_month','built_year','access_info','floor_count_text','total_units','google_place_id','google_lat','google_lng'):
        if column in columns:
            conn.execute(f'UPDATE buildings SET {column}=COALESCE(NULLIF({column},\'\'),(SELECT {column} FROM buildings WHERE building_id=?)) WHERE building_id=?',(drop,keep))
    for alias,target in aliases.items():
        if canonical_key(target,aliases) == drop:
            conn.execute('UPDATE building_key_aliases SET canonical_key=?,updated_at=CURRENT_TIMESTAMP WHERE alias_key=?',(keep,alias))
    conn.execute('INSERT INTO building_key_aliases(alias_key,canonical_key) VALUES (?,?) ON CONFLICT(alias_key) DO UPDATE SET canonical_key=excluded.canonical_key,updated_at=CURRENT_TIMESTAMP',(drop,keep))
    conn.execute('DELETE FROM buildings WHERE building_id=?',(drop,))
    updated=dict(conn.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
    for alias in updated:canonical_key(alias,updated)
