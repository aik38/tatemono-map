from pathlib import Path
import json

from tatemono_map.cloud.realpro_batch import update_batch,apply_publication_scope,fukuoka_address
from tatemono_map.cloud.public_db import export_public,readonly
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild


def item(rows,company='テスト管理 福岡営業所'):
    defaults=dict(category='realpro',updated_at='2026-10-23',file='test.pdf',room='101',
        building_name='新規正確マンション',address='北九州市小倉北区魚町9-8-7',rent_man=5.5,
        fee_man=0.3,area_sqm=25,layout='1K',raw_block='test',page=1)
    return dict(metadata=dict(company=company,sha256='a'*64,filename='test.pdf',pages=1,
        acquired_at='2026-10-23T22:00:00+09:00',gcs_ref={}),errors=[],warnings=[],
        rows=[{**defaults,**r,'evidence_id':f'pdf:test.pdf#p=1#t=1#i={i}','source_room_id':str(i)} for i,r in enumerate(rows)])


def initialize(master,tmp_path):
    with connect(master) as c:
        c.execute("INSERT INTO ingest_runs(source,snapshot_key,status) VALUES ('existing','baseline','completed')")
        run=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('UPDATE listings SET ingest_run_id=?',(run,))
        c.execute("INSERT INTO current_ingest_snapshots(source,ingest_run_id) VALUES ('existing',?)",(run,))
    rebuild(str(master))
    baseline=tmp_path/'baseline.sqlite3';export_public(master,baseline)
    return baseline


def test_fukuoka_scope_and_preserve_explicit_outside_addresses():
    from tatemono_map.cli.pdf_batch_run import complement_address_with_ward,RealproParser
    assert fukuoka_address('福岡県久留米市東町1-2-3')
    assert not fukuoka_address('佐賀県鳥栖市東町1-2-3')
    assert complement_address_with_ward('広島市中区西白島町22-60','門司区')=='広島市中区西白島町22-60'
    result=RealproParser()._extract_context_from_lines(['北九州市門司区/北九州市若松区/福...',
        'エルカーサ門司駅前','北九州市門司区梅ノ木町3-8','軽量鉄骨造地上3階 / 2017年07月築'])
    assert result[0]=='エルカーサ門司駅前'


def test_batch_retains_fukuoka_in_master_and_excludes_from_public_and_is_idempotent(master,tmp_path):
    baseline=initialize(master,tmp_path)
    data=[item([{},dict(building_name='福岡保存マンション',address='福岡市中央区天神9-8-7'),
        dict(building_name='県外除外マンション',address='鳥栖市東町9-8-7')])]
    first=update_batch(master,data,tmp_path,'one',baseline)
    assert first['parsed_rows']==3
    assert first['attached_rows']==2
    assert first['row_counts']=={'accepted_new':2,'held':1}
    with readonly(master) as c:
        assert c.execute("SELECT COUNT(*) FROM buildings WHERE canonical_name='福岡保存マンション'").fetchone()[0]==1
        assert c.execute("SELECT COUNT(*) FROM buildings WHERE canonical_name='県外除外マンション'").fetchone()[0]==0
        history=c.execute('SELECT COUNT(*) FROM listings').fetchone()[0]
    with readonly(tmp_path/'public.sqlite3') as c:
        assert c.execute("SELECT COUNT(*) FROM buildings WHERE canonical_name='福岡保存マンション'").fetchone()[0]==0
    second=update_batch(master,data,tmp_path,'two',baseline)
    assert second['attached_rows']==0 and second['row_counts']=={'duplicate':3}
    with readonly(master) as c:assert c.execute('SELECT COUNT(*) FROM listings').fetchone()[0]==history
    with connect(master) as c:c.execute("UPDATE cloud_publication_settings SET value='fukuoka' WHERE key='area'")
    apply_publication_scope(master,baseline)
    export_public(master,tmp_path/'expanded.sqlite3',baseline=baseline)
    with readonly(tmp_path/'expanded.sqlite3') as c:
        assert c.execute("SELECT COUNT(*) FROM buildings WHERE canonical_name='福岡保存マンション'").fetchone()[0]==1


def test_conflicting_provider_unit_held_and_prior_ulucks_unchanged(master,tmp_path):
    baseline=initialize(master,tmp_path)
    data=[item([{},dict(rent_man=6)])]
    result=update_batch(master,data,tmp_path,'conflict',baseline)
    assert result['attached_rows']==0 and result['counts_before']==result['counts_after']
    assert result['row_counts']=={'anomaly':2}
