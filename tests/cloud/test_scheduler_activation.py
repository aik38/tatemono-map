import json
import subprocess

import pytest
from test_setup import module


@pytest.mark.parametrize('state,schedule,expected_resumes', [('PAUSED','0 4 * * 1',1),('ENABLED','0 4 * * 1',0),('PAUSED','* * * * *',0)])
def test_scheduler_activation_validates_target_and_preserves_existing_enabled_job(monkeypatch,state,schedule,expected_resumes):
    mod=module('enable_scheduler')
    for k,v in {'GCP_PROJECT_ID':'tatemono-map','GCP_REGION':'asia-northeast1','GCP_JOB':'tatemono-collection-poc','GCP_SCHEDULER_JOB':'weekly'}.items():monkeypatch.setenv(k,v)
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        data={'state':state,'schedule':schedule,'timeZone':'Asia/Tokyo','httpTarget':{'uri':'https://run.googleapis.com/v2/projects/tatemono-map/locations/asia-northeast1/jobs/tatemono-collection-poc:run'}}
        return subprocess.CompletedProcess(args,0,json.dumps(data),'')
    monkeypatch.setattr(mod.subprocess,'run',run)
    if schedule!='0 4 * * 1':
        with pytest.raises(RuntimeError,match='contract_changed'):mod.main()
    else:mod.main()
    assert sum('resume' in c for c in calls)==expected_resumes
