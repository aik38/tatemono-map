import json
from pathlib import Path

from conftest import make_pdf
from tatemono_map.cloud.pipeline import update_master
from tatemono_map.cloud.public_db import export_public,readonly
from tatemono_map.db.repo import connect
from tatemono_map.cloud.partial import confirm_review


def broad(config):
    return dict(config,area_id='kitakyushu',area_label='北九州',address_contains='kitakyushu')


def setup_scope(master,config,tmp_path,rooms=('101','102')):
    pdf=make_pdf(tmp_path/'old.pdf',rooms=rooms)
    update_master(master,[pdf],len(rooms),config,tmp_path,'narrow')
    baseline=tmp_path/'baseline.sqlite3';export_public(master,baseline)
    return baseline


def test_partial_adopts_good_room_retains_pending_room_and_later_clean_run_expires_it(master,config,tmp_path):
    baseline=setup_scope(master,config,tmp_path)
    good=make_pdf(tmp_path/'good.pdf',rooms=('101',),rent='6万円')
    held=make_pdf(tmp_path/'held.pdf',rooms=('未定',))
    result=update_master(master,[good,held],2,broad(config),tmp_path,'partial',public_baseline=baseline)
    assert result['attached_rows']==1 and result['held_rows']==1 and result['retained_rows']==1
    assert result['public_counts']['vacancies']==3
    with readonly(master) as conn:
        assert conn.execute('SELECT COUNT(*) FROM cloud_collection_rows WHERE ingest_run_id=?',(result['ingest_run_id'],)).fetchone()[0]==2
        assert conn.execute('SELECT COUNT(*) FROM listings WHERE rent_yen=55000').fetchone()[0]>=2
    with readonly(tmp_path/'public.sqlite3') as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'cloud_%' OR name='unmatched_queue'").fetchall()
    clean=update_master(master,[good],1,broad(config),tmp_path,'clean',public_baseline=baseline)
    assert clean['held_rows']==0 and clean['retained_rows']==0
    assert clean['public_counts']['vacancies']==2


def test_all_held_does_not_turn_previous_scope_into_zero(master,config,tmp_path):
    baseline=setup_scope(master,config,tmp_path)
    held=make_pdf(tmp_path/'all-held.pdf',rooms=('未定',))
    report=update_master(master,[held],1,broad(config),tmp_path,'all-held',public_baseline=baseline)
    assert report['attached_rows']==0 and report['held_rows']==1 and report['retained_rows']==2
    assert report['public_counts']['vacancies']==3


def test_same_company_duplicates_are_audited_once_and_conflicting_offers_are_held(master,config,tmp_path):
    baseline=setup_scope(master,config,tmp_path,rooms=('101',))
    a=make_pdf(tmp_path/'a.pdf',rooms=('101',))
    b=make_pdf(tmp_path/'b.pdf',rooms=('101',))
    r=update_master(master,[a,b],2,broad(config),tmp_path,'identical',public_baseline=baseline)
    assert r['attached_rows']==1 and r['duplicate_rows']==1
    with connect(master) as conn:
        conn.execute("UPDATE buildings SET availability_raw='昔の確認済み',structure='確認済み構造' WHERE canonical_name='架空テストマンション'")
    b=make_pdf(tmp_path/'b.pdf',rooms=('101',),rent='6万円')
    r=update_master(master,[a,b],2,broad(config),tmp_path,'conflict',public_baseline=baseline)
    assert r['attached_rows']==0 and r['held_rows']==2 and r['retained_rows']==1
    assert r['public_counts']['vacancies']==2
    with readonly(tmp_path/'public.sqlite3') as conn:
        assert conn.execute("SELECT availability_raw,structure FROM buildings WHERE canonical_name='架空テストマンション'").fetchone()==('昔の確認済み','確認済み構造')


def test_confirmed_review_reused_and_explicit_block_overrides_auto_alias(master,config,tmp_path):
    baseline=setup_scope(master,config,tmp_path,rooms=('101',))
    changed=make_pdf(tmp_path/'changed.pdf',building='まったく異なる名称',rooms=('101',))
    r=update_master(master,[changed],1,broad(config),tmp_path,'held-name',public_baseline=baseline)
    assert r['held_rows']==1 and r['attached_rows']==0
    with connect(master) as conn:
        key=conn.execute('SELECT review_key FROM cloud_collection_rows WHERE ingest_run_id=?',(r['ingest_run_id'],)).fetchone()[0]
        building=conn.execute("SELECT building_id FROM buildings WHERE canonical_name='架空テストマンション'").fetchone()[0]
        confirm_review(conn,key,'match',building,'101','synthetic-reviewer')
    r=update_master(master,[changed],1,broad(config),tmp_path,'confirmed-name',public_baseline=baseline)
    assert r['attached_rows']==1 and r['held_rows']==0
    another=make_pdf(tmp_path/'another-room.pdf',building='まったく異なる名称',rooms=('102',))
    r=update_master(master,[changed,another],2,broad(config),tmp_path,'confirmed-other-room',public_baseline=baseline)
    assert r['attached_rows']==2 and r['held_rows']==0
    with connect(master) as conn:confirm_review(conn,key,'block',building,'101','synthetic-reviewer')
    r=update_master(master,[changed,another],2,broad(config),tmp_path,'blocked-name',public_baseline=baseline)
    assert r['attached_rows']==1 and r['held_rows']==1 and r['retained_rows']==1


def test_literal_leading_zero_rooms_stay_distinct(master,config,tmp_path):
    baseline=setup_scope(master,config,tmp_path,rooms=('101',))
    pdf=make_pdf(tmp_path/'leading-zero.pdf',rooms=('001','1'))
    r=update_master(master,[pdf],2,broad(config),tmp_path,'leading-zero',public_baseline=baseline)
    assert r['attached_rows']==2 and r['duplicate_rows']==0


def test_building_blocks_and_unrelated_names_at_same_address_do_not_auto_merge(master,config,tmp_path):
    baseline=setup_scope(master,config,tmp_path,rooms=('101',))
    with connect(master) as conn:
        conn.execute("UPDATE buildings SET canonical_name='架空A棟' WHERE canonical_name='架空テストマンション'")
    pdf=make_pdf(tmp_path/'block-b.pdf',building='架空B棟',rooms=('101',))
    r=update_master(master,[pdf],1,broad(config),tmp_path,'block-b',public_baseline=baseline)
    assert r['attached_rows']==0 and r['held_rows']==1 and r['retained_rows']==1


def test_individual_invalid_terms_are_tracked_without_stopping_good_rows(master,config,tmp_path):
    baseline=setup_scope(master,config,tmp_path)
    a=make_pdf(tmp_path/'normal.pdf',rooms=('101',))
    b=make_pdf(tmp_path/'invalid.pdf',rooms=('102',),rent='0円')
    r=update_master(master,[a,b],2,broad(config),tmp_path,'bad-terms',public_baseline=baseline)
    assert r['attached_rows']==1 and r['anomaly_rows']==1 and r['retained_rows']==1
    assert sum(r['row_counts'].values())==2


def test_isolated_scope_error_is_private_and_previous_room_is_retained(master,config,tmp_path):
    baseline=setup_scope(master,config,tmp_path)
    good=make_pdf(tmp_path/'good.pdf',rooms=('101',),rent='6万円')
    bad=make_pdf(tmp_path/'bad.pdf',address='福岡県福岡市中央区天神1-1-1',rooms=('102',))
    result=update_master(master,[good,bad],2,broad(config),tmp_path,'address-partial',public_baseline=baseline)
    assert result['attached_rows']==1 and result['anomaly_rows']==1
    assert result['retained_rows']==1
    with readonly(master) as conn:
        row=conn.execute("SELECT classification,reason FROM cloud_collection_rows WHERE ingest_run_id=? AND room_raw='102'",(result['ingest_run_id'],)).fetchone()
        assert tuple(row)==('anomaly','invalid_scope_address')
    assert result['public_counts']['vacancies']==3


def test_widespread_scope_errors_stop_the_company(master,config,tmp_path):
    import pytest
    from tatemono_map.cloud.collector import CollectionError
    baseline=setup_scope(master,config,tmp_path)
    bad=make_pdf(tmp_path/'bad.pdf',address='福岡県福岡市中央区天神1-1-1',rooms=('101','102','103'))
    good=make_pdf(tmp_path/'good.pdf',rooms=('104',))
    with pytest.raises(CollectionError,match='out_of_scope_address'):
        update_master(master,[good,bad],4,broad(config),tmp_path,'widespread',public_baseline=baseline)
