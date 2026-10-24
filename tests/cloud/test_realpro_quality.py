import json
from collections import Counter

from tatemono_map.building_registry import ingest_master_import as imp
from tatemono_map.cloud import realpro_quality as quality
from tatemono_map.cloud.realpro_batch import update_batch
from tatemono_map.cloud.public_db import readonly
from test_realpro_batch import item,initialize


def test_lot_gate_only_changes_realpro_and_keeps_ambiguous_addresses_private(master):
    from tatemono_map.db.repo import connect
    for address in ['久留米市合川町2142-3','大牟田市飯田町7-1','飯塚市伊川250-1']:
        assert not imp._has_minimum_address_granularity(address)
        assert imp._has_realpro_lot_address(address)
        with connect(master) as c:
            assert imp._can_auto_seed(c,'正確な新規住宅',address,'unmatched','realpro')[0]
            assert not imp._can_auto_seed(c,'正確な新規住宅',address,'unmatched','ulucks')[0]
            assert not imp._can_auto_seed(c,'正確な新規住宅',address,'unmatched','mansion_review_chintai')[0]
    for address in ['久留米市合川町2142','久留米市合川町2142-3?4','久留米市合川町2142-3、4',
                    '久留米市合川町2142-3(地番)','久留米市合川町2142~2143','久留米市合川町2142--3']:
        assert not imp._has_realpro_lot_address(address)


def test_verified_repair_preserves_original_inputs_history_snapshots_and_is_idempotent(master,tmp_path,monkeypatch):
    baseline=initialize(master,tmp_path)
    data=[item([{},dict(building_name='正確な新規賃貸住宅',address='北九州市小倉南区徳力777-2'),
        dict(building_name='正確な新規賃貸住宅',address='北九州市小倉南区徳力777-2',room='102'),
        dict(building_name='原本不一致住宅',address='北九州市小倉南区徳力778-2'),
        dict(building_name='原本住所不足住宅',address='北九州市小倉南区徳力779'),
        dict(building_name='原本住所不明住宅',address='北九州市小倉南区徳力780-1?2')])]
    gate=imp._has_realpro_lot_address
    monkeypatch.setattr(imp,'_has_realpro_lot_address',lambda _:False)
    first=update_batch(master,data,tmp_path,'original',baseline)
    assert first['row_counts']=={'accepted_new':1,'held':5}
    monkeypatch.setattr(imp,'_has_realpro_lot_address',gate)
    proofs={}
    with readonly(master) as c:
        c.row_factory=__import__('sqlite3').Row
        rows=quality.current_rows(c)
        old_snapshots=list(c.execute('SELECT * FROM current_ingest_snapshots'))
        old_inputs=list(c.execute('SELECT * FROM realpro_pdf_inputs'))
        for row in rows:
            raw=json.loads(row['raw_json'])
            proofs['a'*64,raw['source_room_id']]=dict(page=1,name=raw['building_name'],address=raw['address'],room=raw['room'],
                layout_area='1K 25m2',rent='55,000円',fee='3,000円')
        original_listings=[tuple(r) for r in c.execute('SELECT * FROM listings ORDER BY listing_key')]
    proofs['a'*64,'3']['rent']='56,000円'
    monkeypatch.setattr(quality,'source_index',lambda *args:(proofs,dict(pdf_count=1,pdf_pages=1,source_room_ids=6,unverified=[])))
    report=quality.repair_candidate(master,baseline,None,tmp_path,'repair')
    assert report['rescued_count']==2
    assert report['row_counts']['held']==3
    assert report['new_buildings']==1
    with readonly(master) as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM current_ingest_snapshots')]==[tuple(r) for r in old_snapshots]
        assert [tuple(r) for r in c.execute('SELECT * FROM realpro_pdf_inputs')]==[tuple(r) for r in old_inputs]
        now={r[0]:tuple(r) for r in c.execute('SELECT * FROM listings')}
        assert all(now[r[0]]==r for r in original_listings)
        n=len(now)
    second=quality.repair_candidate(master,baseline,None,tmp_path,'repair-again')
    assert second['rescued_count']==0
    with readonly(master) as c:assert c.execute('SELECT count(*) FROM listings').fetchone()[0]==n


def test_realpro_conflict_fast_bound_preserves_existing_decisions(master):
    from tatemono_map.db.repo import connect
    with connect(master) as c:
        for name in ['架空テストマンション','架空テストマンションA','架空テストマンションB','別棟住宅',
                     '他社テストマンション','新規住宅','レジデンスアルファ','レジデンスベータ']:
            for address in ['北九州市小倉北区魚町1-1-1','北九州市門司区港町2-2-2','久留米市合川町2142-3']:
                assert imp._has_close_conflict(c,name,address,fast=True)==imp._has_close_conflict(c,name,address)


def test_repair_exact_name_guard_holds_near_identical_same_address_buildings(master,tmp_path):
    import pandas as pd
    from tatemono_map.cli.pdf_batch_run import write_master_import_csv
    from tatemono_map.db.repo import connect
    with connect(master) as c:
        c.execute("UPDATE buildings SET canonical_name='グランドレジデンスA',norm_name='グランドレジデンスA' WHERE canonical_name='架空テストマンション'")
    data=item([dict(building_name='グランドレジデンスB',address='北九州市小倉北区魚町1-1-1')])
    path=tmp_path/'exact.csv';write_master_import_csv(pd.DataFrame(data['rows']),path)
    result=imp.ingest_master_import_csv(str(master),str(path),source='realpro',snapshot_source='realpro:repair-test',
        snapshot_key='test',strict_name_match=True,exact_name_match=True)
    assert result.attached_listings==0
    with readonly(master) as c:
        assert c.execute("SELECT reason FROM unmatched_queue WHERE ingest_run_id=?",(result.ingest_run_id,)).fetchone()[0]=='strict_name_match_unconfirmed'
