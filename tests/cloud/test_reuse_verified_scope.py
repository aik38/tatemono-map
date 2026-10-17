from datetime import datetime,timezone
from conftest import make_pdf
from test_batch import all_config
from tatemono_map.cloud.batch import execute_all
from tatemono_map.cloud.run import execute
from tatemono_map.cloud.collector import Collected,CollectionError,ORIGIN
import pytest


def test_explicit_verified_head_reuse_avoids_reacquiring_company8_and_counts_new_buildings_once(store,config,tmp_path):
    cfg=dict(config,area_id='kitakyushu',area_label='北九州',address_contains='kitakyushu',auto_seed_high_confidence=True)
    pdf=make_pdf(tmp_path/'company8.pdf',building='全域新規架空施設アルファ',address='北九州市小倉南区架空町4-8-3')
    work=tmp_path/'stage-a';work.mkdir()
    evidence={'acquired_at':datetime.now(timezone.utc).isoformat()}
    a=execute(store,cfg,{},work,'a'*40,collector=lambda *args:Collected([pdf],1,False,evidence))
    assert a['report']['new_buildings']==1
    catalog=[{'company_id':str(i),'search_url':ORIGIN+'/company/lists/'+str(i)} for i in (8,26)]
    acquired=[]
    def collect(one,credentials,root,emit):
        emit(None,catalog)
        for target in catalog:
            if emit(target,None) is True:continue
            acquired.append(target['company_id'])
            emit(dict(one,**target,company_label='架空業者'+target['company_id']),Collected([pdf],1,False,evidence))
        return catalog
    work=tmp_path/'stage-b';work.mkdir()
    b=execute_all(store,all_config(cfg),{},work,'b'*40,collector=collect,reuse_release=a['run_id'])
    assert acquired==['26']
    report=b['report']
    assert report['successful_companies']==2 and report['reused_companies']==1
    assert report['pdf_count']==2 and report['newly_acquired_pdf_count']==1
    assert report['parsed_rows']==report['attached_rows']==2
    assert report['cross_company_duplicate_rows']==1 and report['new_buildings']==0
    assert report['counts_before']==a['report']['counts_after']
    assert report['counts_after']['buildings']==a['report']['counts_after']['buildings']


def test_stale_resume_request_refuses_before_collection(store,config,tmp_path):
    work=tmp_path/'work';work.mkdir()
    def unexpected(*args):raise AssertionError('collection must not start')
    with pytest.raises(CollectionError,match='resume_head_changed'):
        execute_all(store,all_config(config),{},work,'b'*40,collector=unexpected,reuse_release='20261017T000000Z-aaaaaaaaaaaa')
