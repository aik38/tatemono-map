import json
import subprocess
from types import SimpleNamespace

import pytest
from google.api_core.exceptions import Forbidden, NotFound, PreconditionFailed

from conftest import MemoryStore
from test_setup import module


def deployment(tmp_path, monkeypatch, config):
    mod = module('deploy_job'); monkeypatch.chdir(tmp_path)
    settings = dict(GCP_PROJECT_ID='tatemono-map', GCP_REGION='asia-northeast1', GCP_JOB='job',
        GCP_BUCKET='private-bucket', GCP_ADOPT_IMAGE='approved', GCP_RUNTIME_SERVICE_ACCOUNT='runtime',
        GCP_SCHEDULER_JOB='weekly', ULUCKS_LOGIN_SECRET='existing-login', GITHUB_SHA='a'*40,
        GITHUB_RUN_ID='123', COLLECTOR_IMAGE='new-image', GITHUB_REF='refs/heads/main',
        GITHUB_REPOSITORY='aik38/tatemono-map', ULUCKS_CONFIG_JSON=json.dumps(config))
    for k,v in settings.items(): monkeypatch.setenv(k,v)
    store = MemoryStore(tmp_path/'objects'); store.claims = {}
    class Blob:
        def __init__(self, name): self.name = name
        def reload(self):
            if self.name not in store.claims: raise NotFound('absent')
        def upload_from_string(self, value, **kw):
            assert kw['if_generation_match'] == 0
            if self.name in store.claims: raise PreconditionFailed('exists')
            store.claims[self.name] = json.loads(value)
    store.bucket = SimpleNamespace(blob=Blob)
    monkeypatch.setattr(mod,'GCSStore',lambda *_: store)
    calls = []; response = {'execute_error':False,'backup_error':False,'executions':[],'after':[]}
    def run(argv, **kw):
        calls.append(argv)
        if argv[1:5] == ['run','jobs','executions','list']:
            rows = response['after'] if any(c[1:4] == ['run','jobs','execute'] for c in calls) else response['executions']
            output = json.dumps(rows)
        elif argv[1:4] == ['run','jobs','describe']:
            output = 'private: PASSWORD_SHOULD_NEVER_BE_PUBLIC' if '--format=export' in argv else ('7' if '--format=value(metadata.generation)' in argv else ('approved' if any('containers[0]' in a for a in argv) else ''))
        else: output = ''
        if argv[1:4] == ['run','jobs','execute'] and response['execute_error']:
            return subprocess.CompletedProcess(argv,1,'','403 token=NEVER_PRINT_THIS storage.objects.get')
        return subprocess.CompletedProcess(argv,0,output,'')
    monkeypatch.setattr(mod.subprocess,'run',run)
    return mod, store, calls, response


def test_backup_verified_before_update_and_rerun_attempt_cannot_execute_twice(tmp_path,monkeypatch,config):
    mod,store,calls,response = deployment(tmp_path,monkeypatch,config)
    mod.main()
    assert len(store.claims) == 1
    receipt = next(iter(store.claims.values()))
    assert receipt['backup']['object'].endswith('-123-1.yaml')
    assert receipt['backup']['generation'] > 0
    assert sum(c[1:4] == ['run','jobs','execute'] for c in calls) == 1
    assert not any(c[1:3] == ['storage','cp'] for c in calls)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','2')
    with pytest.raises(mod.DeploymentError,match='intent_already_exists'): mod.main()
    assert sum(c[1:4] == ['run','jobs','execute'] for c in calls) == 1


def test_failed_backup_and_active_execution_block_job_update(tmp_path,monkeypatch,config):
    mod,store,calls,response = deployment(tmp_path,monkeypatch,config)
    store.fail_upload_prefix = 'deployment-backups/'
    with pytest.raises(mod.DeploymentError,match='private_backup_failed'): mod.main()
    assert not store.claims
    assert not any(c[1:4] in (['run','jobs','update'],['run','jobs','execute']) for c in calls)
    response['executions'] = [{'metadata':{'name':'active'},'status':{}}]
    with pytest.raises(mod.DeploymentError,match='active_cloud_run'): mod.main()
    assert not store.claims


@pytest.mark.parametrize('terminal', [False,True])
def test_uncertain_execution_never_rolls_back_or_reexecutes_and_diagnostics_stay_private(tmp_path,monkeypatch,config,terminal):
    mod,store,calls,response = deployment(tmp_path,monkeypatch,config)
    response['execute_error'] = True
    response['after'] = [{'metadata':{'name':'new'},'status':({'completionTime':'done','conditions':[{'type':'Completed','status':'False'}]} if terminal else {})}]
    with pytest.raises((mod.DeploymentError,SystemExit)) as error: mod.main()
    assert 'NEVER_PRINT_THIS' not in str(error.value)
    assert 'PASSWORD_SHOULD_NEVER_BE_PUBLIC' not in str(error.value)
    # A failed live execution is not rolled back using exported YAML: retain the
    # now-updated Job, immutable prior backup and intentionally paused Scheduler.
    assert not any(c[1:4] == ['run','jobs','replace'] for c in calls)
    assert sum(c[1:4] == ['run','jobs','execute'] for c in calls) == 1
    assert store.claims


def test_public_error_contains_only_status_and_allowlisted_permissions():
    mod = module('deployment_backup')
    secret = 'Authorization: Bearer DO_NOT_PRINT; password=PRIVATE; storage.objects.get'
    result = mod.safe_error(Forbidden(secret))
    assert result == {'status':403,'permissions':['storage.objects.get']}
    assert 'DO_NOT_PRINT' not in json.dumps(result)


def test_deploy_only_never_claims_or_starts_a_collection(tmp_path,monkeypatch,config):
    mod,store,calls,response=deployment(tmp_path,monkeypatch,config)
    monkeypatch.setenv('ULUCKS_DEPLOY_ONLY','true')
    mod.main()
    assert any(c[1:4]==['run','jobs','update'] for c in calls)
    assert not any(c[1:4]==['run','jobs','execute'] for c in calls)
    assert store.claims
