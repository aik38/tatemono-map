from pathlib import Path
import sqlite3

import pytest

from tatemono_map.cloud.public_db import export_public, publication_ids, readonly
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild


def test_wide_private_building_and_aliases_never_reach_public_bytes(master, tmp_path):
    baseline = tmp_path / 'baseline.sqlite3'
    export_public(master, baseline)
    approved, _ = publication_ids(baseline)
    with connect(master) as conn:
        conn.execute("INSERT INTO buildings(building_id,canonical_name,canonical_address,norm_name,norm_address) VALUES ('private-new','PRIVATE_AREA_SENTINEL','PRIVATE_ADDRESS_SENTINEL','PRIVATE_AREA_SENTINEL','PRIVATE_ADDRESS_SENTINEL')")
        conn.execute("INSERT INTO building_key_aliases(alias_key,canonical_key) VALUES ('private-alias','private-new')")
        conn.execute("INSERT INTO building_key_aliases(alias_key,canonical_key) VALUES ('private-new-link',?)", (next(iter(approved)),))
    rebuild(str(master))
    public = tmp_path / 'public.sqlite3'
    export_public(master, public, baseline=baseline)
    assert publication_ids(public) == publication_ids(baseline)
    with readonly(public) as conn:
        for table in ('building_summaries','building_rental_summaries','building_sale_summaries'):
            assert {r[0] for r in conn.execute(f'SELECT building_key FROM {table}')} <= approved
        # Keep an existing building even though it has no advertised vacancies.
        assert conn.execute('SELECT COUNT(*) FROM buildings').fetchone()[0] == len(approved)
    raw = public.read_bytes()
    for forbidden in (b'PRIVATE_AREA_SENTINEL', b'PRIVATE_ADDRESS_SENTINEL', b'private-new', b'private-alias'):
        assert forbidden not in raw


def test_existing_public_building_cannot_silently_disappear(master, tmp_path):
    baseline = tmp_path / 'baseline.sqlite3'
    export_public(master, baseline)
    with sqlite3.connect(master) as conn:
        conn.execute('DELETE FROM buildings WHERE building_id=(SELECT building_id FROM buildings LIMIT 1)')
    with pytest.raises(ValueError, match='existing_public_building_missing'):
        export_public(master, tmp_path / 'public.sqlite3', baseline=baseline)
