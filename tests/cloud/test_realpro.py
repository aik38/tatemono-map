from types import SimpleNamespace
import json

import pandas as pd
import pytest

from tatemono_map.cloud import realpro_pipeline as rp
from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.fetch_public import accounted_collection
from tatemono_map.cloud.public_db import export_public, readonly
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild


def initialize(master):
    with connect(master) as c:
        c.execute("INSERT INTO ingest_runs(source,snapshot_key,status) VALUES ('existing','baseline','completed')")
        run=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('UPDATE listings SET ingest_run_id=?',(run,))
        c.execute("INSERT INTO current_ingest_snapshots(source,ingest_run_id) VALUES ('existing',?)",(run,))
        building=c.execute("SELECT building_id FROM buildings WHERE canonical_name='架空テストマンション'").fetchone()[0]
        c.execute("INSERT INTO listings(listing_key,building_key,name,address,room_label,rent_yen,source_kind,ingest_run_id) VALUES ('ulucks-preserved',?,'架空テストマンション','北九州市小倉北区魚町1-1-1','101',90000,'ulucks',?)",(building,run))
    rebuild(str(master))


def parsed(monkeypatch, rows):
    frame=pd.DataFrame([{**dict(category='realpro',updated_at='2026-10-23',file='sample.pdf',
        building_name='架空テストマンション',address='北九州市小倉北区魚町1-1-1',room='101',
        rent_man=5.5,fee_man=0.3,area_sqm=25,layout='1K',evidence_id=f'pdf:sample#i={i}',
        raw_block='sample'),**row} for i,row in enumerate(rows)])
    monkeypatch.setattr(rp.RealproParser,'parse',lambda *_:SimpleNamespace(df=frame.copy(),warnings=[]))
    monkeypatch.setattr(rp,'page_count_fast',lambda _:1)


def test_realpro_preserves_ulucks_priority_history_and_other_snapshots(master,tmp_path,monkeypatch):
    initialize(master)
    baseline=tmp_path/'baseline.sqlite3';export_public(master,baseline)
    pdf=tmp_path/'sample.pdf';pdf.write_bytes(b'%PDF-test')
    parsed(monkeypatch,[{}])
    cfg={'company_id':'15974'}
    evidence={'expected_rows':1,'regions':[{'label':'北九州市小倉北区'}],'acquired_at':'2026-10-23T00:00:00Z'}
    first=rp.update(master,pdf,evidence,cfg,tmp_path,'first',baseline)
    second=rp.update(master,pdf,evidence,cfg,tmp_path,'second',baseline)
    assert first['attached_rows']==second['attached_rows']==1
    assert accounted_collection(second)
    with readonly(master) as c:
        assert c.execute("SELECT rent_yen FROM listings WHERE listing_key='ulucks-preserved'").fetchone()[0]==90000
        assert c.execute("SELECT COUNT(*) FROM listings WHERE source_kind='realpro'").fetchone()[0]==3
        assert c.execute("SELECT vacancy_count,rent_yen_min FROM building_summaries WHERE building_key=(SELECT building_id FROM buildings WHERE canonical_name='架空テストマンション')").fetchone()==(1,90000)
        assert c.execute("SELECT COUNT(*) FROM current_ingest_snapshots WHERE source='existing'").fetchone()[0]==1


def test_realpro_bad_pdf_count_does_not_update_snapshot(master,tmp_path,monkeypatch):
    initialize(master);parsed(monkeypatch,[{}])
    baseline=tmp_path/'baseline.sqlite3';export_public(master,baseline)
    with pytest.raises(CollectionError,match='accounting'):
        rp.update(master,tmp_path/'missing.pdf',{'expected_rows':2},{'company_id':'15974'},tmp_path,'bad',baseline)
    with readonly(master) as c:
        assert dict(c.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots')).keys()=={'existing'}


def test_realpro_adopts_confident_seed_and_retains_unresolved_previous_offers(master,tmp_path,monkeypatch):
    initialize(master)
    baseline=tmp_path/'baseline.sqlite3';export_public(master,baseline)
    pdf=tmp_path/'sample.pdf';pdf.write_bytes(b'%PDF-test')
    cfg={'company_id':'15974'}
    evidence={'expected_rows':1,'regions':[{'label':'北九州市小倉北区'}],'acquired_at':'2026-10-23T00:00:00Z'}
    parsed(monkeypatch,[{}])
    rp.update(master,pdf,evidence,cfg,tmp_path,'one',baseline)
    parsed(monkeypatch,[{'building_name':'新規安全テストマンション','address':'北九州市小倉北区宇佐町9-8-7','room':'102'},
        {'building_name':'不明物件','address':'','room':'不明'}])
    result=rp.update(master,pdf,{**evidence,'expected_rows':2},cfg,tmp_path,'two',baseline)
    assert result['new_buildings']==1
    assert result['anomaly_rows']==1 and result['retained_rows']==1
    assert accounted_collection(result)
    with readonly(master) as c:
        assert c.execute('SELECT COUNT(*) FROM cloud_retained_listings').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM buildings').fetchone()[0]==3


def test_realpro_scope_header_is_not_property_name():
    from tatemono_map.cli.pdf_batch_run import RealproParser
    context=RealproParser()._extract_context_from_lines([
        '北九州市門司区/北九州市小倉北区/田川市/京都郡苅田町',
        'エテルノカーサ門司港','北九州市門司区大久保2丁目3-28','木造地上2階 / 2011年09月築'])
    assert context[0]=='エテルノカーサ門司港'
    assert context[1]=='北九州市門司区大久保2丁目3-28'
