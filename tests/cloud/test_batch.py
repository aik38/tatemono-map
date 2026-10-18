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
    assert [{k:x[k] for k in ('company_id','code')} for x in head['report']['failed_companies']]==[{'company_id':'26','code':'pdf_rows_do_not_match_result_count'}]
    assert head['report']['failed_companies'][0]['diagnostics']
    assert 'all_company_proof' not in head['report']
    assert any('failed-company-26' in name for name in store.objects)
    assert len([name for name in store.objects if '/companies/' in name and name.endswith('.pdf')])==2


def test_failure_after_mutation_restores_only_that_company(store,config,tmp_path,monkeypatch):
    import tatemono_map.cloud.batch as batch
    cfg=all_config(config)
    a=make_pdf(tmp_path/'a.pdf')
    b=make_pdf(tmp_path/'b.pdf',rent='6万円')
    original=batch.update_master
    def fail_after_write(*args,**kwargs):
        result=original(*args,**kwargs)
        if args[3]['company_id']=='26':raise CollectionError('synthetic_after_mutation')
        return result
    monkeypatch.setattr(batch,'update_master',fail_after_write)
    work=tmp_path/'work';work.mkdir()
    head=batch.execute_all(store,cfg,{},work,'c'*40,collector=fake_catalog(cfg,a,b))
    assert head['report']['successful_companies']==1
    assert head['report']['public_counts']['vacancies']==2
    master=tmp_path/'master-copy.sqlite3';store.download(head['master'],master)
    with readonly(master) as conn:
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE rent_yen=60000").fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE source_kind='ulucks'").fetchone()[0]==1


def test_unavailable_company_preserves_previous_scope_and_all_available_companies_complete(store,config,tmp_path):
    import json
    from tatemono_map.cloud.wide import CompanyUnavailable
    from tatemono_map.cloud.run import all_company_proof_ready
    cfg=all_config(config)
    a=make_pdf(tmp_path/'a.pdf')
    b=make_pdf(tmp_path/'b.pdf',rooms=('202',))
    first=tmp_path/'first';first.mkdir()
    old=execute_all(store,cfg,{},first,'c'*40,collector=fake_catalog(cfg,a,b))
    result_file=tmp_path/'old-result.json'
    store.download(old['report']['company_results'][1]['result_ref'],result_file)
    previous=json.loads(result_file.read_text())
    catalog=[{'company_id':str(i),'search_url':ORIGIN+'/company/lists/'+str(i)} for i in (8,26)]
    def collect(config,credentials,root,emit):
        emit(None,catalog)
        emit(catalog[0],None)
        emit(dict(config,**catalog[0],company_label='架空業者8'),Collected([a],1,False,{}))
        emit(catalog[1],None)
        emit(catalog[1],CompanyUnavailable({'notice':'synthetic private access notice','request_sent':False}))
        return catalog
    work=tmp_path/'next';work.mkdir()
    new=execute_all(store,cfg,{},work,'c'*40,collector=collect)
    assert new['report']['successful_companies']==1 and new['report']['company_count']==2
    assert new['report']['failed_companies']==[]
    assert len(new['report']['unavailable_companies'])==1
    assert new['report']['public_counts']['vacancies']==old['report']['public_counts']['vacancies']==3
    assert all_company_proof_ready(new,'c'*40)
    master=tmp_path/'master-next.sqlite3';store.download(new['master'],master)
    with readonly(master) as conn:
        assert conn.execute('SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?',(previous['scope_key'],)).fetchone()[0]==previous['ingest_run_id']
    marker=fetch(store,tmp_path/'pub-next.sqlite3',tmp_path/'marker-next.json')
    assert 'synthetic private access notice' not in json.dumps(marker)
