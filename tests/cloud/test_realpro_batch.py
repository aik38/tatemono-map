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


def test_same_address_different_name_never_authorizes_a_match(master,tmp_path):
    baseline=initialize(master,tmp_path)
    data=[item([dict(building_name='全く別の建物',address='北九州市小倉北区魚町1-1-1')])]
    result=update_batch(master,data,tmp_path,'name-conflict',baseline)
    assert result['attached_rows']==0 and result['row_counts']=={'held':1}
    assert result['counts_before']==result['counts_after']


def test_pdf_money_conversion_preserves_whole_yen_exactly():
    from tatemono_map.cli.master_import import _parse_man_to_yen
    assert _parse_man_to_yen('3.03')==30300
    assert _parse_man_to_yen('4.31')==43100
    assert _parse_man_to_yen('0.57')==5700
    assert _parse_man_to_yen('0')==0
    assert _parse_man_to_yen('') is None


def test_reused_workdir_preserves_all_duplicate_originals_before_parser_failure(tmp_path,monkeypatch):
    import hashlib,zipfile,pytest
    from tatemono_map.cloud import realpro_batch as batch
    archive=tmp_path/'inputs.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('new-one.pdf',b'%PDF-identical-source')
        z.writestr('new-two.pdf',b'%PDF-identical-source')
    work=tmp_path/'work';(work/'originals').mkdir(parents=True)
    (work/'originals'/'stale-from-old-batch.pdf').write_bytes(b'%PDF-old')
    class Store:
        def __init__(self):self.objects={}
        def upload_verified(self,path,name):
            content=path.read_bytes()
            if name in self.objects:assert self.objects[name]==content
            self.objects[name]=content
            return {'object':name,'generation':1,'sha256':hashlib.sha256(content).hexdigest()}
    store=Store();parsed=[]
    def fail(pdf,cache):
        assert sum('/originals/' in name for name in store.objects)==2
        parsed.append(pdf.name)
        raise ValueError('synthetic_unreadable_pdf')
    monkeypatch.setattr(batch,'parse_pdf',fail)
    with pytest.raises(ValueError,match='pdf_source_accounting_or_context_failed'):
        batch.execute(store,archive,work,'a'*40,expected_pdfs=2)
    assert parsed==['new-one.pdf','new-two.pdf']
    assert sum('/originals/' in name for name in store.objects)==2
    assert sum('/analysis/' in name for name in store.objects)==2
    assert not (work/'master.sqlite3').exists()


def test_realpro_release_preserves_verified_ulucks_census_reference():
    import pytest
    from tatemono_map.cloud.realpro_batch import preserve_ulucks_catalog
    old_run='20261018T190110Z-9aa6143e7cf5';new_run='20261023T182821Z-886d59ee8c82'
    reference={'object':f'private-runs/{old_run}/company-catalog.json','generation':123,'sha256':'a'*64}
    head={'run_id':old_run,'report':{'company_catalog_ref':reference,'company_ids':['4','8']}}
    class Store:
        def clone_verified(self,ref,name):
            assert ref==reference and name==f'private-runs/{new_run}/company-catalog.json'
            return {**ref,'object':name,'generation':456}
    report={'source':'realpro','pdf_count':99}
    preserve_ulucks_catalog(Store(),head,new_run,report)
    assert report['company_ids']==['4','8']
    assert report['inherited_ulucks_collection_run_id']==old_run
    assert report['source']=='realpro' and report['pdf_count']==99
    assert report['company_catalog_ref']['generation']==456
    assert head['report']['company_catalog_ref']==reference
    invalid={'run_id':new_run,'report':head['report']}
    with pytest.raises(ValueError,match='previous_company_catalog_reference_invalid'):
        preserve_ulucks_catalog(Store(),invalid,new_run,{})
