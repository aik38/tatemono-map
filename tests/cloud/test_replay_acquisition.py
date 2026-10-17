"""Saved acquisitions remain pinned to the observed company and original time."""
import json
from datetime import datetime,timezone
from types import SimpleNamespace
from google.api_core.exceptions import NotFound
import pytest
from conftest import make_pdf,MemoryStore
from test_batch import all_config
from tatemono_map.cloud.replay import replay_company
from tatemono_map.cloud.collector import ORIGIN,CollectionError
from tatemono_map.cloud.batch import execute_all
from tatemono_map.ulucks_geography import AREA_LABELS

RUN='20261017T220240Z-17086bbe5dd5'

def saved_acquisition(store,config,tmp_path,changed_company=None):
    one=dict(all_config(config),company_id='4',company_label='架空取得会社',search_url=ORIGIN+'/company/lists/4')
    pdf=make_pdf(tmp_path/'original.pdf')
    ref=store.upload(pdf,f'private-runs/{RUN}/companies/4/pdf/000.pdf')
    time=datetime.now(timezone.utc).isoformat()
    evidence={'company_id':'4','scope_verified':True,'area_labels':list(AREA_LABELS),'search_counts':[1],'acquired_at':time}
    file=tmp_path/'evidence.json';file.write_text(json.dumps(evidence))
    eref=store.upload(file,f'private-runs/{RUN}/company-4-evidence.json')
    manifest={'config':dict(one,company_id=changed_company or '4'),'expected_rows':1,'confirmed_zero':False,'pdfs':[ref],'evidence':eref}
    file=tmp_path/'manifest.json';file.write_text(json.dumps(manifest))
    store.upload(file,f'private-runs/{RUN}/company-4-manifest.json')
    class Blob:
        def __init__(self,name):self.name=name
        def reload(self):
            if self.name not in store.objects:raise NotFound('missing')
            self.ref,self.path=store.objects[self.name]
            self.generation=self.ref['generation'];self.size=self.path.stat().st_size
        def download_as_bytes(self,if_generation_match):
            assert if_generation_match==self.generation
            return self.path.read_bytes()
    store.bucket=SimpleNamespace(blob=Blob)
    return {'company_id':'4','search_url':one['search_url']},time,pdf

def test_replay_uses_original_pdf_and_time_and_does_not_reacquire(store,config,tmp_path):
    target,time,pdf=saved_acquisition(store,config,tmp_path)
    work=tmp_path/'batch';work.mkdir()
    def collect(cfg,creds,root,emit):
        emit(None,[target])
        assert emit(target,None) is True
        return [target]
    head=execute_all(store,all_config(config),{},work,'b'*40,collector=collect,replay_acquisition_run=RUN)
    report=head['report']
    assert report['successful_companies']==1 and report['parsed_rows']==report['attached_rows']==1
    assert report['pdf_count']==1 and report['newly_acquired_pdf_count']==0
    assert report['replayed_acquisition_companies']==1
    result_ref=report['company_results'][0]['result_ref']
    file=tmp_path/'result.json';store.download(result_ref,file)
    assert json.loads(file.read_text())['acquired_at']==time

def test_cross_company_manifest_is_rejected_before_pdf_download(store,config,tmp_path):
    target,_,_=saved_acquisition(store,config,tmp_path,changed_company='26')
    store.downloads.clear()
    with pytest.raises(CollectionError,match='scope_identity_changed'):
        replay_company(store,RUN,target,all_config(config),tmp_path/'replay')
    assert not store.downloads
    assert replay_company(store,RUN,{'company_id':'6','search_url':ORIGIN+'/company/lists/6'},all_config(config),tmp_path/'missing') is None
