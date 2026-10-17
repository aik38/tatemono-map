import copy

import pytest

from conftest import make_pdf
from tatemono_map.cloud.batch import execute_all
from tatemono_map.cloud.collector import Collected, CollectionError, ORIGIN
from tatemono_map.cloud.fetch_public import fetch
from tatemono_map.cloud.public_db import readonly


def all_config(config):
    return dict(config,collection_mode='all_companies',area_id='kitakyushu',area_label='北九州',
        address_contains='kitakyushu',company_id='all',company_label='全業者',search_url=ORIGIN+'/company')


def fake_catalog(base, first, second, bad_second=False):
    catalog=[{'company_id':str(i),'search_url':ORIGIN+'/company/lists/'+str(i)} for i in (8,26)]
    def collect(config, credentials, root, emit):
        emit(None,catalog)
        for target,pdf in zip(catalog,(first,second)):
            emit(target,None)
            one=dict(base,**target,company_label='架空業者'+target['company_id'])
            emit(one,Collected([pdf],2 if bad_second and target['company_id']=='26' else 1,False,{'acquired_at':'2026-10-18T00:00:00Z'}))
        return catalog
    return collect


def test_batch_one_release_all_history_final_public_terms_and_dedup(store, config, tmp_path):
    cfg=all_config(config)
    a=make_pdf(tmp_path/'a.pdf')
    b=make_pdf(tmp_path/'b.pdf',rent='6.0万円')
    work=tmp_path/'work';work.mkdir()
    head=execute_all(store,cfg,{},work,'c'*40,collector=fake_catalog(cfg,a,b))
    assert head['report']['company_count']==head['report']['successful_companies']==2
    assert head['report']['parsed_rows']==head['report']['attached_rows']==2
    assert head['report']['pdf_count']==2
    assert head['report']['cross_company_duplicate_rows']==1
    assert head['report']['public_counts']['vacancies']==2
    marker=fetch(store,tmp_path/'public.sqlite3',tmp_path/'marker.json')
    assert any(p['rent_yen_min']==60000 and p['vacancy_count']==1 for p in marker['proof'])
    master=tmp_path/'verified.sqlite3';store.download(head['master'],master)
    with readonly(master) as conn:
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE source_kind='ulucks'").fetchone()[0]==2
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE source_kind='realpro'").fetchone()[0]==1


def test_failed_company_is_rolled_back_while_healthy_company_updates(store,config,tmp_path):
    cfg=all_config(config)
    a=make_pdf(tmp_path/'a.pdf')
    b=make_pdf(tmp_path/'b.pdf')
    before=copy.deepcopy(store.read_head())
    work=tmp_path/'work';work.mkdir()
    head=execute_all(store,cfg,{},work,'c'*40,collector=fake_catalog(cfg,a,b,bad_second=True))
    assert store.read_head()!=before
    assert head['report']['successful_companies']==1
    assert head['report']['failed_companies']==[{'company_id':'26','code':'pdf_rows_do_not_match_result_count'}]
    assert 'all_company_proof' not in head['report']
    assert any('failed-company-26' in name for name in store.objects)
    assert len([name for name in store.objects if '/companies/' in name and name.endswith('.pdf')])==2
