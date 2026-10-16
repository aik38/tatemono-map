#!/usr/bin/env bash
# One command in the existing authenticated Cloud Shell; no Secret writes.
set -euo pipefail
umask 077
reviewed_commit="${1:?Usage: bash cloud/complete_initial_release.sh FULL_REVIEWED_MAIN_SHA [EXISTING_CHECKOUT]}"
checkout="${2:-$HOME/work/tatemono-ulucks-first-connect}"
cd "$checkout"
mkdir -p work/initial-release
exec 9>work/initial-release/entrypoint.lock
flock -n 9 || { echo 'Another first-release entrypoint is running.'; exit 1; }
python3 - "$reviewed_commit" <<'PY'
import datetime,json,os,pathlib,re,subprocess,sys
expected=sys.argv[1]
root=pathlib.Path.cwd()
report=root/'work/initial-release/handoff.private.json'
state={'schema':2,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewed_commit':expected,'stages':[],'production_verified':False}
# Preserve previous diagnostics and progress rather than replacing the evidence.
if report.exists():
    copy=report.with_name('handoff-before-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.private.json')
    copy.write_bytes(report.read_bytes())
def save():
    tmp=report.with_suffix('.tmp')
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(report)
def run(name,args,capture=True):
    print('Stage: '+name,flush=True)
    result=subprocess.run(args,text=True,capture_output=True)
    state['stages'].append({'name':name,'returncode':result.returncode,'stdout':result.stdout if capture else '', 'stderr':result.stderr})
    save()
    if result.returncode: raise RuntimeError(name+'_failed')
    return result.stdout.strip()
try:
    if len(expected)!=40 or any(c not in '0123456789abcdef' for c in expected): raise RuntimeError('full_reviewed_sha_required')
    if run('tracked_changes',['git','status','--porcelain','--untracked-files=no']): raise RuntimeError('tracked_changes_preserved_no_checkout')
    if run('repository',['git','config','--get','remote.origin.url']) not in ('https://github.com/aik38/tatemono-map.git','git@github.com:aik38/tatemono-map.git'): raise RuntimeError('wrong_repository')
    run('fetch_main',['git','fetch','origin','main'])
    if run('main_sha',['git','rev-parse','origin/main'])!=expected: raise RuntimeError('latest_main_differs_from_reviewed_sha')
    before=run('previous_checkout',['git','rev-parse','HEAD'])
    run('code_backup',['git','branch','--no-track','backup/initial-entry-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'),before])
    run('reviewed_checkout',['git','checkout','--detach',expected])
    run('gcp_identity',['gcloud','auth','list','--filter=status:ACTIVE','--format=value(account)'])
    run('github_identity',['gh','auth','status'])
    python=root/'work/gcp-setup-venv/bin/python'
    if not python.exists(): run('venv',['python3','-m','venv',str(python.parent.parent)])
    run('dependencies',[str(python),'-m','pip','install','--quiet','-e','.', '-r','requirements-cloud.txt'])
    env=dict(os.environ);env['PYTHONPATH']=str(root/'src')
    print('Stage: initial_release (private checkpoint, transfer, collection and production verification)',flush=True)
    operation_started=datetime.datetime.now(datetime.timezone.utc).timestamp()
    progress=root/'work/initial-release/progress.private.json'
    prior=json.loads(progress.read_text()) if progress.exists() else {}
    runner='cloud/recover_initial_deployment.py' if prior.get('setup_complete') and prior.get('deployment_run_id') else 'cloud/initial_release.py'
    result=subprocess.run([str(python),runner,'--activate','--reviewed-commit',expected],env=env,text=True,capture_output=True)
    state['stages'].append({'name':'initial_release','runner':runner,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    progress=root/'work/initial-release/progress.private.json'
    if progress.exists():state['progress']=json.loads(progress.read_text())
    for name in ('audit.private.json','expected-release.private.json','completed-evidence.private.json','setup/bootstrap/bootstrap-progress.private.json','recovery-evidence.private.json','recovery-error.private.json'):
        path=root/'work/initial-release'/name
        if path.exists():state[name]=json.loads(path.read_text())
    error=root/'work/initial-release/last-error.private.log'
    if result.returncode and error.exists() and error.stat().st_mtime>=operation_started:state['last_command_error']=error.read_text()
    if result.returncode:
        settings=root/'work/setup.private.json'
        if settings.exists():
            cfg=json.loads(settings.read_text())
            query=f'resource.type="cloud_run_job" AND resource.labels.job_name="{cfg["job"]}" AND timestamp>="{state["started_at"]}" AND (log_id("run.googleapis.com/stdout") OR log_id("run.googleapis.com/stderr"))'
            logs=subprocess.run(['gcloud','logging','read',query,'--project',cfg['project'],'--limit=30','--format=json'],text=True,capture_output=True)
            state['cloud_run_diagnostic']={'returncode':logs.returncode,'stderr':logs.stderr}
            if logs.returncode==0:
                records=json.loads(logs.stdout);state['cloud_run_diagnostic']['records']=records
                run_ids=set()
                for record in records:
                    value=record.get('jsonPayload')
                    if not isinstance(value,dict):
                        try:value=json.loads(record.get('textPayload',''))
                        except (ValueError,TypeError):continue
                    run_id=value.get('run_id','')
                    if isinstance(run_id,str) and re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}',run_id):run_ids.add(run_id)
                for run_id in sorted(run_ids):
                    detail=subprocess.run(['gcloud','storage','cat',f'gs://{cfg["bucket"]}/private-runs/{run_id}/failure.json'],text=True,capture_output=True)
                    if detail.returncode==0:state.setdefault('collection_failures',[]).append(json.loads(detail.stdout))
        raise RuntimeError('initial_release_failed_see_consolidated_private_diagnostic')
    state['production_verified']=state.get('progress',{}).get('production_verified') is True
    if not state['production_verified']:raise RuntimeError('production_not_verified')
    state['status']='verified';save()
    print('Verified production release. Private evidence: '+str(report))
except Exception as exc:
    state['status']='stopped';state['reason']=str(exc);save()
    print('Stopped safely: '+str(exc)+'. Private diagnostic: '+str(report),file=sys.stderr)
    sys.exit(1)
PY
