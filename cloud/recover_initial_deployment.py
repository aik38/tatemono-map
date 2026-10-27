#!/usr/bin/env python3
"""Recover the reviewed first deployment's pre-update backup failure, not setup."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from initial_release import REPO, EXPECTED, command, checkpoint, observe_deployment, verify_production
from deployment_backup import safe_error
from tatemono_map.cloud.collector import CollectionError

LEGACY_COMMIT = '2379cfc9f2edd614224d5eba48d294d4fdfed6a7'
BACKUP_FAILURE = 'GCP deployment operation failed: storage cp work/previous-job.yaml'


def failed_before_update(state):
    """Only the reviewed legacy script's failure before update is recoverable."""
    if state.get('commit') != LEGACY_COMMIT or not state.get('setup_complete') or not state.get('deployment_run_id'):
        raise RuntimeError('unreviewed_deployment_failure_phase')
    run = command(['gh','api',f"repos/{REPO}/actions/runs/{state['deployment_run_id']}"], json_output=True)
    if (run.get('head_sha') != state['commit'] or run.get('event') != 'workflow_dispatch'
            or run.get('path') != '.github/workflows/cloud_deploy.yml'
            or run.get('status') != 'completed' or run.get('conclusion') != 'failure'
            or run.get('display_title') != 'Ulucks initial ' + state['nonce']):
        raise RuntimeError('previous_deployment_not_confirmed_failed')
    jobs = command(['gh','api',run['jobs_url'] + '?per_page=100'], json_output=True)['jobs']
    deploy = [j for j in jobs if j['name'] == 'deploy' and j['conclusion'] == 'failure']
    if len(deploy) != 1:
        raise RuntimeError('previous_failed_deploy_job_ambiguous')
    # GitHub Actions logs may contain ANSI color escapes. Capture them privately;
    # never display their raw contents on the terminal or in public diagnostics.
    log = command(['gh','api',f"repos/{REPO}/actions/jobs/{deploy[0]['id']}/logs", '--allow-escape-sequences'])
    if BACKUP_FAILURE not in log or 'Private Job backup verified;' in log:
        raise RuntimeError('previous_failure_not_confirmed_before_job_update')
    return run


def active_executions(rows):
    return [r for r in rows if not r.get('status', {}).get('completionTime')]


def prepare_recovery(state, commit, config, directory, store, gc):
    from google.api_core.exceptions import NotFound
    from tatemono_map.cloud.bootstrap import verify_registered
    from tatemono_map.cloud.public_db import sha256
    run = failed_before_update(state)
    command(['git','merge-base','--is-ancestor',state['commit'],commit])
    pushes = command(['gh','api',f'repos/{REPO}/actions/workflows/cloud_deploy.yml/runs?event=push&head_sha={commit}&per_page=100'], json_output=True)['workflow_runs']
    if not pushes:
        raise RuntimeError('reviewed_main_push_not_visible')
    for push in pushes:
        command(['gh','run','watch',str(push['id']),'--repo',REPO,'--exit-status'])
    running = command(['gh','api',f'repos/{REPO}/actions/workflows/cloud_deploy.yml/runs?per_page=100'], json_output=True)['workflow_runs']
    if any(r['status'] != 'completed' for r in running):
        raise RuntimeError('another_deployment_workflow_active')
    head, generation = store.read_head()
    verify_registered(store, head, generation, directory / 'setup/bootstrap',
        EXPECTED, commit, previous_commits=[state['commit'], *state.get('previous_reviewed_commits', [])], bucket=config['bucket'])
    job = json.loads(gc('run','jobs','describe',config['job'],'--region',config['region'],'--format=json'))
    from tatemono_map.cloud.gcp_inventory import job_inventory
    image = job_inventory(job)['spec']['template']['spec']['template']['spec']['containers'][0]['image']
    if image != state.get('expected_image'):
        raise RuntimeError('previous_job_changed_after_backup_failure')
    executions = json.loads(gc('run','jobs','executions','list','--job',config['job'],'--region',config['region'],'--format=json'))
    if active_executions(executions):
        raise RuntimeError('active_execution_refusing_recovery')
    # Also reject a separately started/completed run after the legacy failure.
    failed_at = datetime.fromisoformat(run['created_at'].replace('Z','+00:00'))
    if any(datetime.fromisoformat(r['metadata']['creationTimestamp'].replace('Z','+00:00')) >= failed_at for r in executions):
        raise RuntimeError('execution_since_failed_deployment_requires_review')
    scheduler = json.loads(gc('scheduler','jobs','describe',config['scheduler_job'],'--location',config['region'],'--format=json(state,schedule,timeZone)'))
    if scheduler != {'state':'PAUSED','schedule':'0 14 * * 4','timeZone':'Asia/Tokyo'}:
        raise RuntimeError('scheduler_not_paused_with_reviewed_schedule')
    # The old CLI can have created its object before failing. Never overwrite it.
    name = f"deployment-backups/{state['commit']}-{run['id']}-{run.get('run_attempt', 1)}.yaml"
    blob = store.bucket.blob(name)
    try:
        blob.reload()
    except NotFound:
        previous_backup = {'object': name, 'status':'absent'}
    else:
        snapshot = directory / 'previous-job-check.private.yaml'
        snapshot.write_text(gc('run','jobs','describe',config['job'],'--region',config['region'],'--format=export'))
        snapshot.chmod(0o600)
        previous_backup = {'object':name,'generation':int(blob.generation),'sha256':sha256(snapshot)}
        checked = directory / 'previous-backup-check.private.yaml'
        try:
            store.download(previous_backup, checked)
        finally:
            checked.unlink(missing_ok=True)
            snapshot.unlink(missing_ok=True)
    # Query only error/authorization fields; never export Job config or tokens.
    principal = 'tm-github-deploy@tatemono-map.iam.gserviceaccount.com'
    query = (f'protoPayload.authenticationInfo.principalEmail="{principal}" '
             f'AND timestamp>="{run["created_at"]}" AND timestamp<="{run["updated_at"]}" '
             'AND protoPayload.status.code!=0')
    try:
        audits = gc('logging','read',query,'--limit=30','--format=json(protoPayload.status,protoPayload.authorizationInfo,protoPayload.methodName)')
        audit = {'available': True, 'summary': safe_error(audits), 'records': json.loads(audits)}
    except RuntimeError:
        audit = {'available':False, 'reason':'audit_access_unavailable'}
    prefix = f"projects/_/buckets/{config['bucket']}/objects/deployment-backups/"
    condition = f"expression=resource.name.startsWith('{prefix}'),title=tatemono-job-config-backup"
    policy = json.loads(gc('storage','buckets','get-iam-policy','gs://' + config['bucket'],'--format=json'))
    member = 'serviceAccount:' + principal
    def bound(role):
        return any(b['role'] == role and member in b.get('members', []) and b.get('condition', {}).get('expression') == f"resource.name.startsWith('{prefix}')" for b in policy.get('bindings', []))
    if not bound('roles/storage.objectCreator'):
        raise RuntimeError('existing_backup_creator_binding_changed')
    evidence = {'previous_workflow':run['id'], 'previous_attempt':run.get('run_attempt',1),
        'previous_backup':previous_backup, 'head':head,'head_generation':generation,
        'audit':audit, 'backup_create_binding_verified':True,
        'backup_read_binding_was_present':bound('roles/storage.objectViewer')}
    checkpoint(directory / 'recovery-evidence.private.json', evidence)
    if not bound('roles/storage.objectViewer'):
        gc('storage','buckets','add-iam-policy-binding','gs://' + config['bucket'],
           '--member',member,'--role=roles/storage.objectViewer','--condition',condition)
    # The only permission addition is readback on this private object prefix.
    # SDK object operations need no bucket metadata/list/delete permission.
    recovery = {'target_commit':commit,'nonce':'recovery-' + commit[:20],
        'previous_progress':dict(state), 'baseline_head':head,'baseline_head_generation':generation,
        'previous_backup':previous_backup}
    state['deployment_recovery'] = recovery
    state['commit'] = commit
    return recovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--reviewed-commit', required=True)
    parser.add_argument('--config', type=Path, default=Path('work/setup.private.json'))
    args = parser.parse_args(); os.umask(0o077)
    if not args.activate:
        raise RuntimeError('explicit_activation_required')
    directory = Path('work/initial-release'); path = directory / 'progress.private.json'
    lock = (directory / 'lock').open('w'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state = json.loads(path.read_text()); config = json.loads(args.config.read_text())
    commit = command(['git','rev-parse','HEAD'])
    if (commit != args.reviewed_commit or command(['gh','api',f'repos/{REPO}/git/ref/heads/main','--jq','.object.sha']) != commit
            or command(['git','status','--porcelain','--untracked-files=no'])):
        raise RuntimeError('recovery_requires_clean_reviewed_main')
    if config['project'] != 'tatemono-map' or config['region'] != 'asia-northeast1':
        raise RuntimeError('unexpected_recovery_project_or_region')
    variables = command(['gh','variable','list','--repo',REPO,'--json','name,value'], json_output=True)
    if not any(v['name'] == 'CLOUD_ENABLED' and v['value'] == 'true' for v in variables):
        raise RuntimeError('recovery_requires_existing_cloud_enabled_state')
    def gc(*items):
        return command(['gcloud',*items,'--project',config['project'],'--quiet'])
    from google.cloud import storage
    from google.oauth2.credentials import Credentials
    from tatemono_map.cloud.storage import GCSStore
    token = gc('auth','print-access-token')
    store = GCSStore(config['bucket'], client=storage.Client(project=config['project'], credentials=Credentials(token)))
    recovery = state.get('deployment_recovery')
    if recovery is None:
        recovery = prepare_recovery(state, commit, config, directory, store, gc)
        checkpoint(path,state)
    if recovery['target_commit'] != commit:
        raise RuntimeError('recovery_commit_changed_observe_previous_attempt')
    endpoint = f'repos/{REPO}/actions/workflows/cloud_deploy.yml/runs?event=workflow_dispatch&per_page=100'
    if not recovery.get('deployment_run_id'):
        if not recovery.get('dispatch_intent'):
            actual, generation = store.read_head()
            if actual != recovery['baseline_head'] or generation != recovery['baseline_head_generation']:
                raise RuntimeError('head_changed_before_recovery_dispatch')
            recovery['dispatch_intent'] = True; checkpoint(path,state)
            command(['gh','workflow','run','cloud_deploy.yml','--repo',REPO,'--ref','main','-f','activation_id=' + recovery['nonce']])
        run = observe_deployment(endpoint, recovery['nonce'], commit)
        if not run:
            raise RuntimeError('recovery_dispatch_pending_no_duplicate')
        recovery['deployment_run_id'] = run['id']; state['deployment_run_id'] = run['id']; checkpoint(path,state)
    run_id = recovery['deployment_run_id']
    print(f'Deployment: https://github.com/{REPO}/actions/runs/{run_id}', flush=True)
    command(['gh','run','watch',str(run_id),'--repo',REPO,'--exit-status'])
    state['collection_workflow_success'] = True; checkpoint(path,state)
    verify_production(state,commit,config,directory,path)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        message = str(exc) if isinstance(exc, (RuntimeError, CollectionError)) else json.dumps({'type':type(exc).__name__, **safe_error(exc)})
        directory = Path('work/initial-release'); directory.mkdir(parents=True, exist_ok=True)
        raw = directory / 'recovery-error.private.log'
        raw.write_text(str(exc)); raw.chmod(0o600)
        checkpoint(directory / 'recovery-error.private.json', {'reason':message})
        raise SystemExit('Stopped safely; recovery progress retained. ' + message) from None
