"""Run authorized maintenance with execution-only overrides on existing runtime."""
import argparse
import base64
import io
import json
import os
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--read-existing');parser.add_argument('--mode',choices=['audit','plan','commit'],default='audit');args=parser.parse_args()
    buf=io.BytesIO()
    paths=['cloud/quality_audit.py','cloud/quality_execute.py','src/tatemono_map/cloud/legacy_rent_evidence.py','src/tatemono_map/cloud/quality.py','src/tatemono_map/normalize/effective_rentals.py','src/tatemono_map/building_registry/merge.py']
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,p)
    encoded=base64.b64encode(buf.getvalue()).decode()
    remote="""import os,base64,io,zipfile,tempfile,runpy
from pathlib import Path
os.environ['GCP_BUCKET']=os.environ['TATEMONO_BUCKET']
with tempfile.TemporaryDirectory() as d:
 os.chdir(d)
 zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD))).extractall(d)
 import sys
 import importlib
 for package in ('tatemono_map','tatemono_map.cloud','tatemono_map.normalize','tatemono_map.building_registry'):
  module=importlib.import_module(package)
  module.__path__.insert(0,str(Path(d)/'src'/package.replace('.','/')))
 os.environ['QUALITY_MODE']=__TASK_MODE__
 os.environ['QUALITY_SOURCE_COMMIT']=__TASK_COMMIT__
 runpy.run_path(TARGET,run_name='__main__')
""".replace('PAYLOAD',repr(encoded)).replace('__TASK_MODE__',repr(args.mode)).replace('__TASK_COMMIT__',repr(os.environ['GITHUB_SHA'])).replace('TARGET',repr('cloud/quality_audit.py' if args.mode=='audit' else 'cloud/quality_execute.py'))
    base=['gcloud','--project',os.environ['GCP_PROJECT_ID'],'--quiet']
    def gc(args):
        r=subprocess.run(base+args,text=True,capture_output=True,timeout=1200)
        if r.returncode:raise RuntimeError('quality_operator_command_failed: '+r.stderr[-1600:])
        return r.stdout
    job=os.environ['GCP_JOB'];region=os.environ['GCP_REGION']
    if args.read_existing:
        execution=args.read_existing
    else:
        active=json.loads(gc(['run','jobs','executions','list','--job',job,'--region',region,'--format=json']))
        if any(not x.get('status',{}).get('completionTime') for x in active):
            raise RuntimeError('another_execution_active')
        assert '~' not in remote
        result=json.loads(gc(['run','jobs','execute',job,'--region',region,'--args=^~^-c~'+remote,'--wait','--format=json']))
        execution=result['metadata']['name']
    print('QUALITY_EXECUTION='+json.dumps({'name':execution}),flush=True)
    query='resource.type="cloud_run_job" AND resource.labels.job_name="'+job+'" AND labels."run.googleapis.com/execution_name"="'+execution+'"'
    for attempt in range(12):
        logs=json.loads(gc(['logging','read',query,'--limit=1000','--order=asc','--format=json']))
        lines=[x.get('textPayload','') for x in logs]
        safe=[line for line in lines if line.startswith(('QUALITY_AUDIT_CHUNK=','QUALITY_AUDIT_END='))]
        end=next((int(line.split('=')[1]) for line in safe if line.startswith('QUALITY_AUDIT_END=')),None)
        indices={int(line.split('=',1)[1].split(':',1)[0]) for line in safe if line.startswith('QUALITY_AUDIT_CHUNK=')}
        if end is not None and indices==set(range(end)):
            for line in safe:print(line,flush=True)
            return
        time.sleep(5)
    raise RuntimeError('maintenance_log_delivery_incomplete_read_existing_execution')

if __name__=='__main__':main()
