import pytest

from tatemono_map.cloud.public_db import id_fingerprint
from tatemono_map.cloud.verify_public import compare


def test_complete_public_id_set_is_verified_even_for_a_building_outside_collection_proof():
    proof = {'building_key':'a', 'vacancy_count':0, 'rent_yen_min':None, 'rent_yen_max':None}
    marker = {'proof':[proof], 'rendered_buildings':2, 'rendered_ids_sha256':id_fingerprint({'a','b'})}
    rows = [{'id':k, 'vacancy_count':0, 'rent_min':None, 'rent_max':None} for k in ['a','b']]
    compare(marker, rows)
    for bad in [rows[:1], rows + [rows[0]], [rows[0],dict(rows[1],id='private')]]:
        with pytest.raises(ValueError, match='id_set_mismatch'):
            compare(marker,bad)
