from tatemono_map.cloud.run import all_company_proof_ready


def test_weekly_full_collection_requires_complete_proof_for_its_revision():
    head={'qc':'passed','source_commit':'a'*40,'report':{'collection_mode':'all_companies','company_count':69,'successful_companies':69}}
    assert all_company_proof_ready(head,'a'*40)
    assert not all_company_proof_ready(head,'b'*40)
    assert not all_company_proof_ready({**head,'report':{**head['report'],'successful_companies':68}},'a'*40)
    assert not all_company_proof_ready({**head,'report':{**head['report'],'collection_mode':'company8'}},'a'*40)


def test_normal_weekly_execution_does_not_read_prior_proof(monkeypatch,config):
    import json
    from contextlib import nullcontext
    from types import SimpleNamespace
    from tatemono_map.cloud import run,batch
    calls=[]
    monkeypatch.setattr(run,'GCSStore',lambda bucket:SimpleNamespace(collection_lease=lambda owner:nullcontext()))
    monkeypatch.setattr(run,'secret_json',lambda ref:{})
    def execute(*args,**kwargs):
        calls.append((args,kwargs))
        return {'run_id':'synthetic','public':{'sha256':'a'*64},'report':{'collection_status':'partial_success'}}
    monkeypatch.setattr(batch,'execute_all',execute)
    monkeypatch.setattr('sys.argv',['collect'])
    monkeypatch.setenv('TATEMONO_BUCKET','synthetic')
    monkeypatch.setenv('TATEMONO_SOURCE_COMMIT','b'*40)
    monkeypatch.setenv('ULUCKS_LOGIN_SECRET','existing-secret')
    monkeypatch.setenv('ULUCKS_CONFIG_JSON',json.dumps(dict(config,collection_mode='all_companies',area_id='kitakyushu')))
    assert run.main()==0
    assert len(calls)==1
    assert calls[0][1]['reuse_release'] is None
    assert calls[0][1]['replay_acquisition_run'] is None
