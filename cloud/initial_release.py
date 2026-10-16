#!/usr/bin/env python3
"""Private, resumable first activation. Default only audits local inputs.

--activate is an explicit production opt-in, after approval and reviewed main.
No login Secret value is accessed. IAM preparation is never invoked here.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_master import audit
from tatemono_map.cloud.collector import validate_config
from tatemono_map.cloud.pipeline import validate_master, unit_room
from tatemono_map.cloud.collector import normal
from tatemono_map.cloud.public_db import readonly
from tatemono_map.cloud.public_db import sha256

REPO = 'aik38/tatemono-map'
EXPECTED = 'fc14fab7f02f92a7c4941e56dc3688f3f17f2d6886ed3c01d0059003a63c5d3d'
FINGERPRINT = 'a5cf80a955872075ca4811df710b509bf7382d797644005b92733f32a916621d'


def command(args, *, json_output=False):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        # Preserve diagnostic stderr privately, never echo an SDK/CLI payload
        # (or successful access-token stdout) into chat/shared Actions logs.
        directory = Path('work/initial-release')
        directory.mkdir(parents=True, exist_ok=True)
        diagnostic = directory / 'last-error.private.log'
        diagnostic.write_text(result.stderr)
        os.chmod(diagnostic, 0o600)
        raise RuntimeError('operation_failed: ' + ' '.join(args[:3]) + '; see private last-error.private.log')
    return json.loads(result.stdout) if json_output else result.stdout.strip()


def checkpoint(path, state):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        os.chmod(temporary, 0o600)
        json.dump(state, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def check_inputs(master, review):
    if sha256(master) != EXPECTED or Path(str(master) + '-wal').exists():
        raise RuntimeError('initial_master_changed_or_wal_present')
    value = json.loads(review.read_text())
    selected = value['selected']
    actual = audit(master, None, None)
    for field in ('sha256', 'counts', 'canonical_id_fingerprint', 'listing_counts_by_source', 'invalid_current_runs', 'foreign_key_errors', 'latest_completed_run'):
        if actual[field] != selected[field]:
            raise RuntimeError('review_does_not_match_master: ' + field)
    if actual['canonical_id_fingerprint'] != FINGERPRINT:
        raise RuntimeError('canonical_id_contract_changed')
    if any(c.get('candidate') and c.get('sha256') != EXPECTED for c in value.get('previous_candidates', [])):
        raise RuntimeError('another_private_master_requires_review')
    if value.get('ulucks_total_rows') != 4006 or len(value.get('kokurakita_rows', [])) != 2195:
        raise RuntimeError('review_scope_counts_changed')
    if value.get('ownership_decided') is not False:
        raise RuntimeError('unexpected_ownership_claim')
    validate_master(master)
    with readonly(master) as conn:
        # ID continuity is established by the verified public-ID fingerprint;
        # aliases come from this private DB, never regenerated from public data.
        ids = {r[0] for r in conn.execute("SELECT building_id FROM buildings")}
        aliases = dict(conn.execute("SELECT alias_key,canonical_key FROM building_key_aliases"))
        for target in aliases.values():
            seen = set()
            while target not in ids and target in aliases and target not in seen:
                seen.add(target)
                target = aliases[target]
            if target not in ids:
                raise RuntimeError('unresolved_canonical_alias')
        rows = conn.execute("""SELECT address,room_label FROM listings
            WHERE source_kind='ulucks' AND ingest_run_id IN
              (SELECT ingest_run_id FROM current_ingest_snapshots)""")
        for address, room in rows:
            if '小倉北区' in normal(address or ''):
                unit_room(room)
    return actual


def deployment_run(runs, nonce, commit):
    matching = [r for r in runs if r.get('head_sha') == commit and r.get('display_title') == 'Ulucks initial ' + nonce]
    if len(matching) > 1:
        raise RuntimeError('multiple_deployment_runs_require_review')
    return matching[0] if matching else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--reviewed-commit')
    parser.add_argument('--master', type=Path, default=Path('work/initial-input/verified-master.sqlite3'))
    parser.add_argument('--review', type=Path, default=Path('work/final-master-review.private.json'))
    parser.add_argument('--config', type=Path, default=Path('work/setup.private.json'))
    args = parser.parse_args()
    os.umask(0o077)
    directory = Path('work/initial-release')
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / 'lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path = directory / 'progress.private.json'
    state = json.loads(path.read_text()) if path.exists() else {'schema': 1}
    actual = check_inputs(args.master, args.review)
    # Config is a new independent scope: no private legacy keys or inferred owner.
    collection = json.loads(Path('cloud/collection.example.json').read_text())
    collection.update(baseline_reviewed=True, baseline_listing_keys=[], legacy_policy='preserve_unknown')
    validate_config(collection)
    collection_path = directory / 'collection.private.json'
    collection_path.write_text(json.dumps(collection, ensure_ascii=False, indent=2))
    checkpoint(directory / 'audit.private.json', actual)
    print('Local master/review verified. No legacy ownership claimed. No GCP or GitHub changes yet.', flush=True)
    if not args.activate:
        print('Read-only preflight complete. Production requires --activate --reviewed-commit EXACT_MAIN_SHA.')
        return
    commit = command(['git', 'rev-parse', 'HEAD'])
    main_sha = command(['gh', 'api', f'repos/{REPO}/git/ref/heads/main', '--jq', '.object.sha'])
    if args.reviewed_commit != commit or commit != main_sha or command(['git', 'status', '--porcelain', '--untracked-files=no']):
        raise RuntimeError('activation_requires_clean_exact_reviewed_main')
    if state.get('commit', commit) != commit:
        raise RuntimeError('resume_commit_changed')
    state['commit'] = commit
    state.setdefault('nonce', 'initial-' + commit[:20])
    checkpoint(path, state)
    if not args.config.exists():
        args.config.write_text(Path('cloud/setup.example.json').read_text())
    config = json.loads(args.config.read_text())
    if not state.get('setup_complete'):
        # A merge also triggers cloud_deploy on push. Finish that run while cloud
        # mode is still disabled, before enabling it and issuing one dispatch.
        if not state.get('activation_started'):
            variables = command(['gh', 'variable', 'list', '--repo', REPO, '--json', 'name,value'], json_output=True)
            if any(v['name'] == 'CLOUD_ENABLED' and v['value'] == 'true' for v in variables):
                raise RuntimeError('cloud_already_enabled_requires_existing_state_review')
            pushes = command(['gh', 'api', f'repos/{REPO}/actions/workflows/cloud_deploy.yml/runs?event=push&head_sha={commit}&per_page=100'], json_output=True)['workflow_runs']
            if not pushes:
                raise RuntimeError('main_push_workflow_not_visible_resume_later')
            for push in pushes:
                command(['gh', 'run', 'watch', str(push['id']), '--repo', REPO, '--exit-status'])
        # Read-only infrastructure plan captures image without reading Secret payloads.
        setup = [sys.executable, 'cloud/setup_gcp.py', '--config', str(args.config), '--output', str(directory / 'setup')]
        command(setup)
        inventory = json.loads((directory / 'setup/inventory.json').read_text())
        if inventory['needs_bootstrap'] and inventory['gcs_database_candidates']:
            raise RuntimeError('existing_gcs_databases_require_private_review')
        image = inventory['job']['spec']['template']['spec']['template']['spec']['containers'][0]['image']
        # Existing collection Secret may only be the dedicated contract created
        # by this runner in a prior interrupted activation, never silently adopted.
        exists = command(['gcloud', 'secrets', 'list', '--project', config['project'], '--format=json(name)'], json_output=True)
        secret_exists = any(r['name'].rsplit('/', 1)[-1] == config['collection_secret'] for r in exists)
        contract_hash = hashlib.sha256(collection_path.read_bytes()).hexdigest()[:63]
        if secret_exists:
            metadata = command(['gcloud', 'secrets', 'describe', config['collection_secret'], '--project', config['project'], '--format=json'], json_output=True)
            if metadata.get('labels', {}).get('tatemono-contract') != contract_hash:
                raise RuntimeError('collection_contract_metadata_mismatch')
        if secret_exists and not state.get('activation_started'):
            raise RuntimeError('preexisting_collection_contract_requires_review')
        state['activation_started'] = True
        state.setdefault('expected_image', image)
        if state['expected_image'] != image:
            raise RuntimeError('job_changed_during_activation')
        checkpoint(path, state)
        activate = setup + ['--apply', '--activate', '--prepared-iam', '--no-dispatch', '--reviewed-commit', commit,
                            '--expected-job-image', image, '--master', str(args.master), '--master-sha256', EXPECTED]
        activate += ['--collection-file', str(collection_path)]
        command(activate)
        state['setup_complete'] = True
        checkpoint(path, state)
        print('Private master bootstrap and activation complete. Starting reviewed Actions deployment.', flush=True)
    endpoint = f'repos/{REPO}/actions/workflows/cloud_deploy.yml/runs?event=workflow_dispatch&per_page=100'
    runs = command(['gh', 'api', endpoint], json_output=True)['workflow_runs']
    run = deployment_run(runs, state['nonce'], commit)
    if not run:
        if state.get('dispatch_intent'):
            raise RuntimeError('dispatch_outcome_pending_resume_later_no_duplicate_dispatched')
        state['dispatch_intent'] = True
        checkpoint(path, state)
        command(['gh', 'workflow', 'run', 'cloud_deploy.yml', '--repo', REPO, '--ref', 'main', '-f', 'activation_id=' + state['nonce']])
        # Leave intent durable; next invocation discovers the run after API lag.
        runs = command(['gh', 'api', endpoint], json_output=True)['workflow_runs']
        run = deployment_run(runs, state['nonce'], commit)
        if not run:
            raise RuntimeError('deployment_dispatched_resume_same_command_to_observe')
    state['deployment_run_id'] = run['id']
    checkpoint(path, state)
    print('Deployment: https://github.com/' + REPO + '/actions/runs/' + str(run['id']), flush=True)
    command(['gh', 'run', 'watch', str(run['id']), '--repo', REPO, '--exit-status'])
    state['collection_workflow_success'] = True
    checkpoint(path, state)
    # deploy_pages.yml already listens to this workflow's successful completion.
    # Do not dispatch a duplicate Pages run that could cancel the automatic run.
    # Verify live release against GCS; never equate CI or dispatch to publication.
    from google.cloud import storage
    from google.oauth2.credentials import Credentials
    from tatemono_map.cloud.storage import GCSStore, validate_head
    from tatemono_map.cloud.verify_public import verify_site
    token = command(['gcloud', 'auth', 'print-access-token'])
    store = GCSStore(config['bucket'], client=storage.Client(project=config['project'], credentials=Credentials(token)))
    head, _ = store.read_head()
    validate_head(head)
    if head['source_commit'] != commit or head['report'].get('bootstrap') or not head['report'].get('proof'):
        raise RuntimeError('no_successful_collection_for_reviewed_commit')
    marker = {'run_id': head['run_id'], 'public_sha256': head['public']['sha256'], 'proof': head['report']['proof']}
    checkpoint(directory / 'expected-release.private.json', marker)
    verify_site(marker, attempts=40, interval=15)
    scheduler = command(['gcloud', 'scheduler', 'jobs', 'describe', config['scheduler_job'], '--project', config['project'], '--location', config['region'], '--format=json'], json_output=True)
    if scheduler['state'] != 'ENABLED' or scheduler['schedule'] != '0 4 * * 1' or scheduler['timeZone'] != 'Asia/Tokyo':
        raise RuntimeError('weekly_scheduler_not_verified')
    state['production_verified'] = True
    state['run_id'] = head['run_id']
    checkpoint(path, state)
    print('Verified: real collection/QC, private master commit, production data proof and Monday 04:00 JST scheduler.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # No SDK payload, raw Cloud CLI stderr or private row content in logs.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        raise SystemExit('Stopped safely; private progress retained. ' + message) from None
