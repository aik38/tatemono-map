from tatemono_map.building_registry.matcher import match_building
from tatemono_map.building_registry.normalization import normalize_building_input
from tatemono_map.db.repo import connect


def test_exact_historical_pair_keeps_existing_id_without_rewriting_canonical(master):
    value=normalize_building_input('架空別名','北九州市小倉南区架空町1-2-3')
    with connect(master) as conn:
        ids=[r[0] for r in conn.execute('SELECT building_id FROM buildings ORDER BY building_id')]
        canonical=conn.execute('SELECT canonical_address FROM buildings WHERE building_id=?',(ids[0],)).fetchone()[0]
        conn.execute("INSERT INTO building_sources(source,evidence_id,building_id,raw_name,raw_address) VALUES ('ulucks','history',?,?,?)",(ids[0],value.raw_name,value.raw_address))
        result=match_building(conn,value.normalized_name,value.normalized_address,source_address_aliases=True)
        assert result.building_id==ids[0]
        assert conn.execute('SELECT canonical_address FROM buildings WHERE building_id=?',(ids[0],)).fetchone()[0]==canonical
        assert match_building(conn,value.normalized_name,'北九州市小倉南区架空町9-9-9',source_address_aliases=True).building_id is None
        conn.execute('UPDATE buildings SET canonical_name=?,norm_name=?,norm_address=? WHERE building_id=?',(value.raw_name,value.normalized_name,value.normalized_address,ids[1]))
        conflict=match_building(conn,value.normalized_name,value.normalized_address,source_address_aliases=True)
        assert conflict.building_id is None and conflict.reason=='alias_ambiguous'


def test_multi_lot_pair_requires_exact_history_and_unique_id(master):
    value=normalize_building_input('架空複数地番','北九州市小倉南区架空町1-2、1-3')
    with connect(master) as conn:
        ids=[r[0] for r in conn.execute('SELECT building_id FROM buildings ORDER BY building_id')]
        conn.execute("INSERT INTO building_sources(source,evidence_id,building_id,raw_name,raw_address) VALUES ('ulucks','multi1',?,?,?)",(ids[0],value.raw_name,value.raw_address))
        assert match_building(conn,value.normalized_name,value.normalized_address).building_id is None
        assert match_building(conn,value.normalized_name,value.normalized_address,source_address_aliases=True).building_id==ids[0]
        conn.execute("INSERT INTO building_sources(source,evidence_id,building_id,raw_name,raw_address) VALUES ('ulucks','multi2',?,?,?)",(ids[1],value.raw_name,value.raw_address))
        result=match_building(conn,value.normalized_name,value.normalized_address,source_address_aliases=True)
        assert result.building_id is None and result.reason=='alias_ambiguous'


def test_explicit_building_series_is_not_treated_as_a_room_suffix(master):
    from tatemono_map.building_registry.normalization import normalize_ulucks_name
    with connect(master) as conn:
        building=conn.execute('SELECT building_id FROM buildings LIMIT 1').fetchone()[0]
        address='北九州市小倉南区架空町1-2-3'
        conn.execute('UPDATE buildings SET canonical_name=?,norm_address=? WHERE building_id=?',('架空ビル第1',address,building))
        conn.execute("INSERT INTO building_sources(source,evidence_id,building_id,raw_name,raw_address) VALUES ('ulucks','series1',?,?,?)",(building,'架空ビル第1',address))
        name=normalize_ulucks_name('架空ビル第3')
        assert name=='架空ビル第3'
        result=match_building(conn,name,address,source_address_aliases=True)
        assert result.building_id is None and result.reason=='name_suffix_conflict'
