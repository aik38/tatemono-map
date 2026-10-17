#!/usr/bin/env python3
"""GitHub main only: back up Job config privately, update, collect, then resume."""
from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deployment_backup import GCSStore, backup, claim, diagnose, exists, safe_error


class DeploymentError(RuntimeError):
    pass

def main():
    env = os.environ
    os.umask(0o077)
    for key in ("GCP_PROJECT_ID", "GCP_REGION", "GCP_JOB", "GCP_BUCKET", "GCP_ADOPT_IMAGE", "GCP_RUNTIME_SERVICE_ACCOUNT", "GCP_SCHEDULER_JOB", "ULUCKS_LOGIN_SECRET", "GITHUB_SHA", "GITHUB_RUN_ID", "COLLECTOR_IMAGE"):
        if not env.get(key):
            raise SystemExit("missing deployment setting: " + key)
    if not env.get('ULUCKS_CONFIG_JSON') and not env.get('ULUCKS_CONFIG_SECRET'):
        raise SystemExit('missing collection contract')
    if env.get('ULUCKS_EXPANSION_STAGE') in ('company8','all'):
        if not env.get('ULUCKS_CONFIG_JSON'):
            raise SystemExit('expansion_requires_existing_nonsecret_config')
        expanded = json.loads(env['ULUCKS_CONFIG_JSON'])
        if expanded.get('company_id') != '8' or expanded.get('baseline_listing_keys') or expanded.get('legacy_policy') != 'preserve_unknown':
            raise SystemExit('expansion_previous_scope_contract_changed')
        expanded.update(area_id='kitakyushu', area_label='北九州', address_contains='kitakyushu')
        if env['ULUCKS_EXPANSION_STAGE']=='all':
            expanded.update(collection_mode='all_companies',company_id='all',company_label='全業者',search_url='https://kitakyushu.ulucks.jp/company')
        env['ULUCKS_CONFIG_JSON'] = json.dumps(expanded, ensure_ascii=False)
    if env.get('ULUCKS_CONFIG_JSON'):
        from tatemono_map.cloud.collector import validate_config
        validate_config(json.loads(env['ULUCKS_CONFIG_JSON']))
    if env.get("GITHUB_REF") != "refs/heads/main" or env.get("GITHUB_REPOSITORY") != "aik38/tatemono-map":
        raise SystemExit("deployment is restricted to repository main")
    project, region, job = (env[k] for k in ("GCP_PROJECT_ID", "GCP_REGION", "GCP_JOB"))
    store = GCSStore(env['GCP_BUCKET'])
    diagnostic = f"deployment-backups/diagnostics/{env['GITHUB_RUN_ID']}-{env.get('GITHUB_RUN_ATTEMPT', '1')}.log"
    directory = Path('work'); directory.mkdir(exist_ok=True)
    def gc(*args):
        result = subprocess.run(["gcloud", *args, "--project", project, "--quiet"], text=True, capture_output=True)
        if result.returncode:
            diagnose(store, directory, diagnostic, result.stderr)
            raise DeploymentError('gcp_operation_failed ' + '.'.join(args[:3]) + ' ' + json.dumps(safe_error(result.stderr)))
        return result.stdout.strip()
    def executions():
        return json.loads(gc('run','jobs','executions','list','--job',job,'--region',region,'--format=json'))
    intent = f"deployment-backups/execution-intents/{env['GITHUB_RUN_ID']}.json"
    if exists(store, intent):
        raise DeploymentError('execution_intent_already_exists_observe_existing_run')
    prior_executions = executions()
    if any(not row.get('status', {}).get('completionTime') for row in prior_executions):
        raise DeploymentError('active_cloud_run_execution_refusing_duplicate')
    image = gc("run", "jobs", "describe", job, "--region", region, "--format=value(spec.template.spec.template.spec.containers[0].image)")
    managed = gc("run", "jobs", "describe", job, "--region", region, "--format=value(metadata.labels.managed-by)")
    if managed != "tatemono-cloud" and image != env["GCP_ADOPT_IMAGE"]:
        raise SystemExit("existing Job image changed since initial inspection; refusing overwrite")
    # Full prior configuration stays in GCS; it may contain private env settings.
    snapshot = Path("work/previous-job.yaml")
    snapshot.parent.mkdir(exist_ok=True)
    snapshot.write_text(gc("run", "jobs", "describe", job, "--region", region, "--format=export"))
    snapshot.chmod(0o600)
    name = f"deployment-backups/{env['GITHUB_SHA']}-{env['GITHUB_RUN_ID']}-{env.get('GITHUB_RUN_ATTEMPT', '1')}.yaml"
    try:
        ref = backup(store, snapshot, name)
    except Exception as exc:
        diagnose(store, directory, diagnostic, exc)
        raise DeploymentError('private_backup_failed ' + json.dumps(safe_error(exc))) from None
    variables = {
        "TATEMONO_BUCKET": env["GCP_BUCKET"], "TATEMONO_SOURCE_COMMIT": env["GITHUB_SHA"],
        "ULUCKS_CONFIG_SECRET": env.get("ULUCKS_CONFIG_SECRET", ""), "ULUCKS_LOGIN_SECRET": env["ULUCKS_LOGIN_SECRET"],
        "ULUCKS_CONFIG_JSON": env.get("ULUCKS_CONFIG_JSON", ""),
    }
    if any('|' in value for value in variables.values()):
        raise SystemExit('invalid environment delimiter in deployment setting')
    claim(store, intent, {'source_commit': env['GITHUB_SHA'], 'workflow_run_id': env['GITHUB_RUN_ID'],
                         'backup': ref, 'previous_executions': [r['metadata']['name'] for r in prior_executions]})
    print('Private Job backup verified; immutable deployment intent recorded.', flush=True)
    gc("run", "jobs", "update", job, "--region", region, "--image", env["COLLECTOR_IMAGE"],
       "--service-account", env["GCP_RUNTIME_SERVICE_ACCOUNT"], "--command=python", "--args=-m,tatemono_map.cloud.run",
       "--tasks=1", "--parallelism=1", "--max-retries=0", "--task-timeout=21600s" if env.get('ULUCKS_EXPANSION_STAGE')=='all' else "--task-timeout=3600s", "--memory=2Gi", "--cpu=1",
       "--update-env-vars", "^|^" + "|".join(f"{k}={v}" for k, v in variables.items()),
       "--update-labels", f"managed-by=tatemono-cloud,source-commit={env['GITHUB_SHA']}")
    generation = gc("run", "jobs", "describe", job, "--region", region, "--format=value(metadata.generation)")
    try:
        execute_args=['run','jobs','execute',job,'--region',region,'--wait']
        if env.get('ULUCKS_EXPANSION_STAGE')=='all':
            # One reviewed proof execution; the persistent weekly Job retains
            # normal args and waits for this exact revision's complete proof.
            args='--args=-m,tatemono_map.cloud.run,--prove-expansion'
            if env.get('ULUCKS_REUSE_SUCCESSFUL_RELEASE'):
                reuse=env['ULUCKS_REUSE_SUCCESSFUL_RELEASE']
                if reuse=='published':
                    import urllib.request,re
                    with urllib.request.urlopen('https://www.tatemono-map.com/cloud_release.json',timeout=45) as response:
                        reuse=json.load(response)['run_id']
                    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}',reuse):
                        raise DeploymentError('published_release_identity_invalid')
                args+=',--reuse-successful-release,'+reuse
            execute_args.append(args)
        elif env.get('ULUCKS_EXPANSION_STAGE')=='company8' and env.get('ULUCKS_REUSE_ACQUISITION'):
            execute_args.append('--args=-m,tatemono_map.cloud.run,--reuse-acquisition,'+env['ULUCKS_REUSE_ACQUISITION'])
        gc(*execute_args)
    except DeploymentError:
        after = executions()
        new = [r for r in after if r['metadata']['name'] not in {x['metadata']['name'] for x in prior_executions}]
        if len(new) != 1 or not new[0].get('status', {}).get('completionTime') or not any(
                c.get('type') == 'Completed' and c.get('status') == 'False' for c in new[0]['status'].get('conditions', [])):
            raise DeploymentError('execution_outcome_uncertain_no_rollback_or_duplicate; private backup retained') from None
        actual_generation = gc("run", "jobs", "describe", job, "--region", region, "--format=value(metadata.generation)")
        if actual_generation != generation:
            raise SystemExit("collection failed and Job changed concurrently; private backup retained, automatic rollback refused") from None
        # The live job update already succeeded; replacing the old exported YAML
        # is neither guaranteed to work nor safe after an execution has started.
        # Keep the approved new job, immutable backup, and paused Scheduler.
        # A later reviewed release may update it once, after observing this run.
        raise DeploymentError("collection_failed_new_job_retained_backup_preserved") from None
    finally:
        snapshot.unlink(missing_ok=True)
    print("Collection committed successfully. Pages verifies production before enabling the weekly Scheduler.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # SDK exceptions can include complete HTTP payloads; never print them.
        if isinstance(exc, DeploymentError):
            raise SystemExit(str(exc)) from None
        raise SystemExit('deployment_failed ' + json.dumps(safe_error(exc))) from None
