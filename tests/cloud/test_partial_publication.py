import json
import pytest
from conftest import make_pdf
from tatemono_map.cloud.collector import Collected,CollectionError
from tatemono_map.cloud.run import execute
from tatemono_map.cloud.fetch_public import fetch


def test_accounted_partial_release_publishes_only_checked_public_fields(store,config,tmp_path):
    good=make_pdf(tmp_path/'good.pdf')
    held=make_pdf(tmp_path/'held.pdf',rooms=('未定',),building='非公開保留専用名称')
    cfg=dict(config,area_id='kitakyushu',area_label='北九州',address_contains='kitakyushu')
    work=tmp_path/'work';work.mkdir()
    result=execute(store,cfg,{},work,'b'*40,collector=lambda *args:Collected([good,held],2,False,{}))
    assert result['report']['parsed_rows']==2 and result['report']['attached_rows']==1
    output=tmp_path/'published.sqlite3';marker=tmp_path/'marker.json'
    public=fetch(store,output,marker)
    assert set(public)=={'schema','run_id','public_sha256','source_commit','counts','proof'}
    assert '非公開保留専用名称'.encode() not in output.read_bytes()
    assert 'review_key' not in marker.read_text() and '非公開保留専用名称' not in marker.read_text()
    store.head['report']['row_counts']['held']=0
    with pytest.raises(CollectionError,match='release_has_no_successful_collection_proof'):
        fetch(store,tmp_path/'invalid.sqlite3',tmp_path/'invalid.json')


def test_all_held_is_a_valid_preserving_release_not_a_fake_zero(store,config,tmp_path):
    pdf=make_pdf(tmp_path/'held.pdf',rooms=('未定',))
    cfg=dict(config,area_id='kitakyushu',area_label='北九州',address_contains='kitakyushu')
    work=tmp_path/'work';work.mkdir()
    head=execute(store,cfg,{},work,'c'*40,collector=lambda *args:Collected([pdf],1,False,{}))
    assert head['report']['attached_rows']==0 and head['report']['held_rows']==1
    assert head['report']['acquisition_status']=='pdf_verified'
    marker=fetch(store,tmp_path/'public.sqlite3',tmp_path/'marker.json')
    assert marker['run_id']==head['run_id']
