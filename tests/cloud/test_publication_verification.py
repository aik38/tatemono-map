import pytest

from tatemono_map.cloud.public_db import id_fingerprint
from tatemono_map.cloud.verify_public import compare


def test_alias_contradicting_two_canonical_identities_never_removes_a_page(master):
    from tatemono_map.db.repo import connect
    from tatemono_map.cloud.public_db import rendered_ids
    from tatemono_map.render.build import _load_buildings
    with connect(master) as c:
        ids = [r[0] for r in c.execute('SELECT building_id FROM buildings')]
        c.execute('INSERT INTO building_key_aliases(alias_key,canonical_key) VALUES (?,?)', ids)
    assert rendered_ids(master) == set(ids)
    assert {b['building_key'] for b in _load_buildings(str(master))[0]} == set(ids)


def test_complete_public_id_set_is_verified_even_for_a_building_outside_collection_proof():
    proof = {'building_key':'a', 'vacancy_count':0, 'rent_yen_min':None, 'rent_yen_max':None}
    marker = {'proof':[proof], 'rendered_buildings':2, 'rendered_ids_sha256':id_fingerprint({'a','b'})}
    rows = [{'id':k, 'vacancy_count':0, 'rent_min':None, 'rent_max':None} for k in ['a','b']]
    compare(marker, rows)
    for bad in [rows[:1], rows + [rows[0]], [rows[0],dict(rows[1],id='private')]]:
        with pytest.raises(ValueError, match='id_set_mismatch'):
            compare(marker,bad)
