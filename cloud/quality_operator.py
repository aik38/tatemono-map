"""Run authorized maintenance with execution-only overrides on existing runtime."""
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
    buf=io.BytesIO()
    paths=['cloud/quality_audit.py']
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,p)
    encoded=base64.b64encode(buf.getvalue()).decode()
    remote="""import os,base64,io,zipfile,tempfile,runpy
from pathlib import Path
os.environ['GCP_BUCKET']=os.environ['TATEMONO_BUCKET']
with tempfile.TemporaryDirectory() as d:
 os.chdir(d)
 zipfile.ZipFile(io.BytesIO(base64.b64decode(PAYLOAD))).extractall(d)
 runpy.run_path('cloud/quality_audit.py',run_name='__main__')
""".replace('PAYLOAD',repr(encoded))
    base=['gcloud','--project',os.environ['GCP_PROJECT_ID'],'--quiet']
    def gc(args):
        r=subprocess.run(base+args,text=True,capture_output=True,timeout=1200)
        if r.returncode:raise RuntimeError('quality_operator_command_failed: '+r.stderr[-1600:])
        return r.stdout
    job=os.environ['GCP_JOB'];region=os.environ['GCP_REGION']
    active=json.loads(gc(['run','jobs','executions','list','--job',job,'--region',region,'--format=json']))
    if any(not x.get('status',{}).get('completionTime') for x in active):
        raise RuntimeError('another_execution_active')
    start=datetime.now(timezone.utc).isoformat()
    assert '~' not in remote
    result=json.loads(gc(['run','jobs','execute',job,'--region',region,'--args=^~^-c~'+remote,'--wait','--format=json']))
    print('QUALITY_EXECUTION='+json.dumps({'name':result['metadata']['name']}),flush=True)
    query='resource.type="cloud_run_job" AND resource.labels.job_name="'+job+'" AND timestamp>="'+start+'"'
    for attempt in range(12):
        logs=json.loads(gc(['logging','read',query,'--limit=1000','--order=asc','--format=json']))
        lines=[x.get('textPayload','') for x in logs]
        safe=[line for line in lines if line.startswith(('QUALITY_AUDIT_CHUNK=','QUALITY_AUDIT_END='))]
        if any(line.startswith('QUALITY_AUDIT_END=') for line in safe):
            for line in safe:print(line,flush=True)
            return
        time.sleep(5)
    raise RuntimeError('maintenance_log_delivery_incomplete_read_existing_execution')

if __name__=='__main__':main()
