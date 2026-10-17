from tatemono_map.building_registry.matcher import match_building
from tatemono_map.building_registry.normalization import normalize_building_input
from tatemono_map.db.repo import connect


def test_normalization_reuse_never_caches_a_database_match_decision(master):
    value=normalize_building_input('別名アルファ','福岡県北九州市小倉北区魚町1-1-1')
    with connect(master) as conn:
        ids=[r[0] for r in conn.execute('SELECT building_id FROM buildings ORDER BY building_id')]
        conn.execute('UPDATE buildings SET norm_address=?',(value.normalized_address,))
        conn.execute("INSERT INTO building_sources(source,evidence_id,building_id,raw_name,raw_address) VALUES ('ulucks','alias1',?,'別名アルファ',?)",(ids[0],value.raw_address))
        assert match_building(conn,value.normalized_name,value.normalized_address).building_id==ids[0]
        # A new source makes the alias ambiguous even though its text has
        # already been normalized. Every decision must inspect current rows.
        conn.execute("INSERT INTO building_sources(source,evidence_id,building_id,raw_name,raw_address) VALUES ('ulucks','alias2',?,'別名アルファ',?)",(ids[1],value.raw_address))
        changed=match_building(conn,value.normalized_name,value.normalized_address)
        assert changed.building_id is None
        assert changed.reason=='alias_ambiguous'
