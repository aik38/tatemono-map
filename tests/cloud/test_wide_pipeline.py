from pathlib import Path

from conftest import make_pdf
from tatemono_map.cloud.pipeline import update_master, scope_key
from tatemono_map.cloud.pipeline import unit_room, CollectionError
import pytest
from tatemono_map.cloud.public_db import export_public, readonly
from tatemono_map.cloud.wide import area_of


def wide(config, **kwargs):
    return dict(config, area_id='kitakyushu',area_label='北九州',address_contains='kitakyushu', **kwargs)


def test_replace_narrow_scope_without_losing_its_history(master, config, pdf, tmp_path):
    update_master(master,[pdf],1,config,tmp_path,'narrow')
    baseline = tmp_path/'baseline.sqlite3'
    export_public(master,baseline)
    with readonly(master) as c:
        old_run=c.execute('SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?',(scope_key(config),)).fetchone()[0]
        old_rows=c.execute('SELECT * FROM listings WHERE ingest_run_id=?',(old_run,)).fetchall()
    broad=wide(config)
    result=update_master(master,[pdf],1,broad,tmp_path,'wide',public_baseline=baseline)
    with readonly(master) as c:
        assert c.execute('SELECT * FROM listings WHERE ingest_run_id=?',(old_run,)).fetchall()==old_rows
        assert c.execute('SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?',(scope_key(config),)).fetchone() is None
        assert c.execute('SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?',(scope_key(broad),)).fetchone()
    assert result['public_counts']['vacancies']==2


def test_managed_companies_share_a_room_without_double_count_and_recover_old_offer(master, config, pdf, tmp_path):
    baseline=tmp_path/'baseline.sqlite3'
    export_public(master,baseline)
    a=wide(config)
    b=dict(a,company_id='26',company_label='架空別業者',search_url='https://kitakyushu.ulucks.jp/company/lists/26')
    update_master(master,[pdf],1,a,tmp_path,'a1',public_baseline=baseline)
    result=update_master(master,[pdf],1,b,tmp_path,'b1',public_baseline=baseline)
    assert result['public_counts']['vacancies']==2
    assert result['legacy_overlap_rows']==1
    second=make_pdf(tmp_path/'second.pdf',rooms=('202',))
    result=update_master(master,[second],1,a,tmp_path,'a2',public_baseline=baseline)
    assert result['public_counts']['vacancies']==3
    with readonly(master) as c:
        assert c.execute("SELECT COUNT(*) FROM listings WHERE source_kind='ulucks'").fetchone()[0]==3


def test_geography_is_anchored_and_includes_counties():
    assert area_of('福岡県北九州市小倉南区長行東1-2-3')=='北九州市小倉南区'
    assert area_of('福岡県遠賀郡水巻町頃末北1-2-3')=='遠賀郡水巻町'
    assert area_of('福岡県福岡市中央区北九州町1-2-3') is None


def test_explicit_source_unit_labels_are_literal_and_unknown_rooms_still_stop():
    for room in ('A','A棟','2-E','C-1'):
        assert unit_room(room,explicit_labels=True)==room
    assert unit_room('A棟',explicit_labels=True)!=unit_room('A',explicit_labels=True)
    assert unit_room('001',explicit_labels=True) != unit_room('1',explicit_labels=True)
    assert unit_room('A-01',explicit_labels=True) != unit_room('A-1',explicit_labels=True)
    for room in ('','未定','不明','-'):
        with pytest.raises(CollectionError,match='identity_ambiguous'):
            unit_room(room,explicit_labels=True)
