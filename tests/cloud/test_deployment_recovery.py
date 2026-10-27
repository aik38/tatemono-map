import copy
import json
import sys
from types import SimpleNamespace

import pytest
from google.api_core.exceptions import NotFound

from conftest import MemoryStore
from test_setup import module, ROOT
from tatemono_map.cloud.bootstrap import prepare, register
from tatemono_map.cloud.public_db import sha256


def recovery(tmp_path, monkeypatch, master):
    mod = module('recover_initial_deployment')
    monkeypatch.setattr(mod,'EXPECTED',sha256(master))
    config = json.loads((ROOT/'cloud/setup.example.json').read_text())
    directory = tmp_path/'work/initial-release'
    store = MemoryStore(tmp_path/'objects')
    state = {'commit':mod.LEGACY_COMMIT,'setup_complete':True,'dispatch_intent':True,
             'deployment_run_id':123,'nonce':'old','expected_image':'approved-image'}
    bootstrap = prepare(master,sha256(master),directory/'setup/bootstrap',mod.LEGACY_COMMIT,bucket=config['bucket'])
    register(store,bootstrap,directory/'setup/bootstrap')
    class Blob:
        def __init__(self,name): self.name=name
        def reload(self):
            if self.name not in store.objects: raise NotFound('missing')
            self.generation=store.objects[self.name][0]['generation']
    store.bucket=SimpleNamespace(blob=Blob)
    calls=[]; responses={'active':False,'bad_log':False,'viewer':False}
    run={'id':123,'head_sha':mod.LEGACY_COMMIT,'path':'.github/workflows/cloud_deploy.yml',
         'event':'workflow_dispatch','status':'completed','conclusion':'failure','display_title':'Ulucks initial old',
         'jobs_url':'repos/example/jobs','created_at':'2026-10-16T13:30:00Z','updated_at':'2026-10-16T13:40:00Z','run_attempt':1}
    def command(argv,**kw):
        calls.append(argv)
        if argv[:2]==['git','merge-base']:return ''
        if argv[:3]==['gh','run','watch']:return ''
        endpoint=argv[2]
        if endpoint.endswith('/123'):return copy.deepcopy(run)
        if endpoint.startswith('repos/example/jobs'):return {'jobs':[{'id':456,'name':'deploy','conclusion':'failure'}]}
        if endpoint.endswith('/456/logs'):return 'other failure' if responses['bad_log'] else mod.BACKUP_FAILURE
        if 'event=push' in endpoint:return {'workflow_runs':[{'id':789}]}
        return {'workflow_runs':[]}
    def gc(*argv):
        calls.append(['gcloud',*argv])
        if argv[:4]==('run','jobs','executions','list'):
            return json.dumps([{'metadata':{'name':'active'},'status':{}}] if responses['active'] else [])
        if argv[:3]==('run','jobs','describe'):
            if '--format=export' in argv:return 'private: unchanged'
            return json.dumps({'apiVersion':'run.googleapis.com/v1','kind':'Job','metadata':{'name':'job'},'spec':{'template':{'spec':{'template':{'spec':{'containers':[{'image':'approved-image'}]}}}}}})
        if argv[:3]==('scheduler','jobs','describe'):return json.dumps({'state':'PAUSED','schedule':'0 14 * * 4','timeZone':'Asia/Tokyo'})
        if argv[:3]==('storage','buckets','get-iam-policy'):
            return json.dumps({'bindings':[{'role':'roles/storage.objectCreator','members':['serviceAccount:tm-github-deploy@tatemono-map.iam.gserviceaccount.com'],'condition':{'expression':f"resource.name.startsWith('projects/_/buckets/{config['bucket']}/objects/deployment-backups/')"}}]})
        if argv[:2]==('logging','read'):return '[]'
        return ''
    monkeypatch.setattr(mod,'command',command)
    return mod,state,config,directory,store,gc,calls,responses


@pytest.mark.parametrize('old_backup_present',[False,True])
def test_recovery_preserves_registered_master_head_old_backup_and_progress(master,tmp_path,monkeypatch,old_backup_present):
    mod,state,config,directory,store,gc,calls,responses=recovery(tmp_path,monkeypatch,master)
    if old_backup_present:
        source=tmp_path/'previous.yaml';source.write_text('private: unchanged')
        store.upload(source,f'deployment-backups/{mod.LEGACY_COMMIT}-123-1.yaml')
    before=copy.deepcopy(state);head=store.read_head()
    objects={name:(copy.deepcopy(ref),path.read_bytes()) for name,(ref,path) in store.objects.items()}
    result=mod.prepare_recovery(state,'b'*40,config,directory,store,gc)
    # The raw legacy Actions log includes ANSI escapes; gh must permit private capture.
    log_calls=[c for c in calls if c[:2]==['gh','api'] and '/456/logs' in c[2]]
    assert len(log_calls)==1 and '--allow-escape-sequences' in log_calls[0]
    assert result['previous_progress']==before
    assert state['setup_complete'] and state['dispatch_intent'] and state['deployment_run_id']==123
    assert state['commit']=='b'*40
    assert store.read_head()==head
    assert {name:(ref,path.read_bytes()) for name,(ref,path) in store.objects.items()}==objects
    assert (result['previous_backup'].get('status')!='absent')==old_backup_present
    bindings=[c for c in calls if 'add-iam-policy-binding' in c]
    assert len(bindings)==1 and '--role=roles/storage.objectViewer' in bindings[0]
    assert 'deployment-backups/' in bindings[0][-1]
    assert not any(c[0]=='gcloud' and ('secrets' in c or 'execute' in c) for c in calls)
    assert not any(c[:3]==['gh','workflow','run'] for c in calls)


@pytest.mark.parametrize('reason',['active','bad_log','changed_backup'])
def test_uncertain_recovery_stops_before_permission_changes_or_dispatch(master,tmp_path,monkeypatch,reason):
    mod,state,config,directory,store,gc,calls,responses=recovery(tmp_path,monkeypatch,master)
    if reason=='changed_backup':
        source=tmp_path/'foreign';source.write_bytes(b'foreign backup')
        store.upload(source,f'deployment-backups/{mod.LEGACY_COMMIT}-123-1.yaml')
    else:responses[reason]=True
    before=copy.deepcopy(state)
    with pytest.raises((RuntimeError,AssertionError)):
        mod.prepare_recovery(state,'b'*40,config,directory,store,gc)
    assert state==before
    assert not any('add-iam-policy-binding' in c or 'execute' in c for c in calls)


def test_known_dispatch_intent_is_observed_without_setup_or_new_dispatch(tmp_path,monkeypatch):
    mod=module('recover_initial_deployment');monkeypatch.chdir(tmp_path)
    directory=tmp_path/'work/initial-release';directory.mkdir(parents=True)
    config=tmp_path/'work/setup.private.json';config.write_text((ROOT/'cloud/setup.example.json').read_text())
    state={'commit':'b'*40,'deployment_recovery':{'target_commit':'b'*40,'nonce':'recovery','dispatch_intent':True}}
    (directory/'progress.private.json').write_text(json.dumps(state))
    calls=[]
    def command(args,**kw):
        calls.append(args)
        if 'rev-parse' in args or '.object.sha' in args:return 'b'*40
        if 'status' in args:return ''
        if args[:3]==['gh','variable','list']:return [{'name':'CLOUD_ENABLED','value':'true'}]
        if args[:3]==['gcloud','auth','print-access-token']:return 'synthetic-token'
        pytest.fail('unexpected operation')
    monkeypatch.setattr(mod,'command',command)
    monkeypatch.setattr(mod,'observe_deployment',lambda *a:None)
    monkeypatch.setattr(mod,'prepare_recovery',lambda *a:pytest.fail('preparation repeated'))
    monkeypatch.setattr('tatemono_map.cloud.storage.GCSStore',lambda *a,**kw:None)
    monkeypatch.setattr(sys,'argv',['recovery','--activate','--reviewed-commit','b'*40])
    with pytest.raises(RuntimeError,match='dispatch_pending_no_duplicate'):mod.main()
    assert not any(c[:3]==['gh','workflow','run'] for c in calls)


def test_recovery_dispatches_once_preserves_old_progress_and_reuses_new_run(tmp_path,monkeypatch):
    mod=module('recover_initial_deployment');monkeypatch.chdir(tmp_path)
    directory=tmp_path/'work/initial-release';directory.mkdir(parents=True)
    config=tmp_path/'work/setup.private.json';config.write_text((ROOT/'cloud/setup.example.json').read_text())
    path=directory/'progress.private.json'
    old={'commit':mod.LEGACY_COMMIT,'setup_complete':True,'dispatch_intent':True,'deployment_run_id':123,'nonce':'old'}
    path.write_text(json.dumps(old));calls=[];verified=[]
    baseline={'run_id':'bootstrap'}
    def prepare(state,commit,*a):
        recovery={'target_commit':commit,'nonce':'new','previous_progress':copy.deepcopy(state),
                  'baseline_head':baseline,'baseline_head_generation':1}
        state['deployment_recovery']=recovery;state['commit']=commit
        return recovery
    def command(args,**kw):
        calls.append(args)
        if 'rev-parse' in args or '.object.sha' in args:return 'b'*40
        if 'status' in args:return ''
        if args[:3]==['gh','variable','list']:return [{'name':'CLOUD_ENABLED','value':'true'}]
        if args[:3]==['gcloud','auth','print-access-token']:return 'synthetic-token'
        if args[:3]==['gh','workflow','run']:
            recorded=json.loads(path.read_text())
            assert recorded['deployment_recovery']['dispatch_intent'] is True
            assert recorded['deployment_recovery']['previous_progress']==old
            return ''
        if args[:3]==['gh','run','watch']:return ''
        pytest.fail(str(args[:3]))
    monkeypatch.setattr(mod,'command',command)
    monkeypatch.setattr(mod,'prepare_recovery',prepare)
    monkeypatch.setattr(mod,'observe_deployment',lambda *a:{'id':456})
    monkeypatch.setattr(mod,'verify_production',lambda *a:verified.append(a[1]))
    monkeypatch.setattr('tatemono_map.cloud.storage.GCSStore',lambda *a,**kw:SimpleNamespace(read_head=lambda:(baseline,1)))
    monkeypatch.setattr(sys,'argv',['recovery','--activate','--reviewed-commit','b'*40])
    mod.main()
    monkeypatch.setattr(mod,'prepare_recovery',lambda *a:pytest.fail('preparation repeated'))
    mod.main()
    assert sum(c[:3]==['gh','workflow','run'] for c in calls)==1
    assert [c[3] for c in calls if c[:3]==['gh','run','watch']]==['456','456']
    assert verified==['b'*40,'b'*40]
