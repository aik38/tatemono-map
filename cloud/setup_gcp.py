#!/usr/bin/env python3
"""One-time, inspect-first GCP/GitHub binding. Default is read-only inventory.

No service-account keys. No bucket/project recreation. No container deployment.
--apply prepares identities and read-only publication access only. Data writes,
deployment privileges and collection require --activate with a reviewed commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPOSITORY = "aik38/tatemono-map"
POOL = "tatemono-github"
PROVIDER = "github-main"
ACCOUNTS = {"runtime": "tm-ulucks-runtime", "deployer": "tm-github-deploy", "publisher": "tm-pages-reader", "scheduler": "tm-weekly-trigger"}
APIS = ("run.googleapis.com", "artifactregistry.googleapis.com", "iam.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com", "secretmanager.googleapis.com", "cloudscheduler.googleapis.com", "storage.googleapis.com")


class SetupError(RuntimeError):
    pass


def command(argv, *, missing=False, json_output=False, stdin=None):
    result = subprocess.run(argv, input=stdin, text=True, capture_output=True)
    if result.returncode:
        if missing and ("NOT_FOUND" in result.stderr or "not found" in result.stderr.lower() or "SERVICE_DISABLED" in result.stderr):
            return None
        # Do not echo raw CLI errors or private settings into public logs.
        raise SetupError("command_failed: " + " ".join(argv[:4]))
    return json.loads(result.stdout) if json_output and result.stdout.strip() else result.stdout.strip()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def provider_contract(project_number, repo_id, owner_id):
    workflows = [f"{REPOSITORY}/.github/workflows/{name}@refs/heads/main" for name in ("cloud_deploy.yml", "deploy_pages.yml")]
    return {
        "attributeMapping": {
            "google.subject": "assertion.sub", "attribute.repository_id": "assertion.repository_id",
            "attribute.role": f"assertion.workflow_ref == '{workflows[0]}' ? 'deployer' : 'publisher'",
        },
        "attributeCondition": f"assertion.repository_id == '{repo_id}' && assertion.repository_owner_id == '{owner_id}' && assertion.repository == '{REPOSITORY}' && assertion.ref == 'refs/heads/main' && assertion.workflow_ref in {json.dumps(workflows)}",
        "issuerUri": "https://token.actions.githubusercontent.com",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="private infrastructure JSON; see cloud/setup.example.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--activate", action="store_true", help="after safety/master review only: bootstrap and enable production")
    parser.add_argument("--reviewed-commit", help="exact reviewed checkout AND main SHA required for activation")
    parser.add_argument("--expected-job-image", help="exact image from inspected inventory; prevents adopting an unexpected Job")
    parser.add_argument("--login-file", type=Path, help="new Secret only: private JSON username/password")
    parser.add_argument("--collection-file", type=Path, help="new Secret only: private collection contract")
    parser.add_argument("--master", type=Path, help="latest verified private master SQLite; never public.sqlite3")
    parser.add_argument("--master-sha256")
    parser.add_argument("--output", type=Path, default=Path("work/gcp-setup"))
    args = parser.parse_args()
    if args.activate and not args.apply:
        raise SetupError("activation_requires_apply")
    if args.activate:
        checkout = command(["git", "rev-parse", "HEAD"])
        main_sha = command(["gh", "api", f"repos/{REPOSITORY}/git/ref/heads/main", "--jq", ".object.sha"])
        if not args.reviewed_commit or args.reviewed_commit != checkout or checkout != main_sha:
            raise SetupError("activation_requires_exact_reviewed_main_commit")
        if command(["git", "status", "--porcelain", "--untracked-files=no"]):
            raise SetupError("activation_requires_clean_reviewed_checkout")
    config = json.loads(args.config.read_text())
    for field in ("project", "region", "bucket", "job", "artifact_repository", "login_secret", "collection_secret", "scheduler_job"):
        if not isinstance(config.get(field), str) or not config[field]:
            raise SetupError("missing_configuration: " + field)
    project, region, bucket, job, registry = (config[k] for k in ("project", "region", "bucket", "job", "artifact_repository"))
    if project != "tatemono-map" or region != "asia-northeast1":
        raise SetupError("unexpected_project_or_region")
    if config['login_secret'] != 'tm-ulucks-login' or config['collection_secret'] != 'tm-ulucks-config':
        raise SetupError("only_dedicated_ulucks_secrets_may_be_bound")
    args.output.mkdir(parents=True, exist_ok=True)
    os.chmod(args.output, 0o700)

    def gc(*items, missing=False, json_output=False):
        return command(["gcloud", *items, "--project", project, "--quiet"], missing=missing, json_output=json_output)

    project_info = gc("projects", "describe", project, "--format=json(projectId,projectNumber)", json_output=True)
    number = str(project_info["projectNumber"])
    bucket_info = gc("storage", "buckets", "describe", "gs://" + bucket, "--format=json", json_output=True)
    bucket_iam = gc("storage", "buckets", "get-iam-policy", "gs://" + bucket, "--format=json", json_output=True)
    if any(member in ("allUsers", "allAuthenticatedUsers") for binding in bucket_iam.get("bindings", []) for member in binding.get("members", [])):
        raise SetupError("bucket_has_public_iam_binding")
    acl_members = [entry.get("entity", "") for entry in bucket_info.get("acl", []) + bucket_info.get("default_acl", [])]
    if any(member in ("allUsers", "allAuthenticatedUsers") for member in acl_members):
        raise SetupError("bucket_has_public_acl")
    if str(bucket_info.get("project_number", "")) != number:
        raise SetupError("bucket_project_mismatch")
    # gcloud storage uses snake_case metadata; require explicit private/uniform bucket.
    if not bucket_info.get("uniform_bucket_level_access"):
        raise SetupError("bucket_requires_uniform_access_review")
    job_info = gc("run", "jobs", "describe", job, "--region", region, "--format=json(metadata.name,metadata.labels,spec.template.spec.template.spec.containers.image,spec.template.spec.template.spec.serviceAccountName)", json_output=True)
    image = job_info["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]["image"]
    previous_account = job_info["spec"]["template"]["spec"]["template"]["spec"].get("serviceAccountName") or f"{number}-compute@developer.gserviceaccount.com"
    if registry == "AUTO":
        repositories = gc("artifacts", "repositories", "list", "--location", region, "--format=json(name,format)", json_output=True)
        candidates = [item["name"].rsplit("/", 1)[-1] for item in repositories if item.get("format") == "DOCKER"]
        observed = re.match(re.escape(f"{region}-docker.pkg.dev/{project}/") + r"([^/]+)/", image)
        if observed and observed[1] in candidates:
            registry = observed[1]
        elif len(candidates) == 1:
            registry = candidates[0]
        else:
            (args.output / "artifact-repositories.json").write_text(json.dumps(repositories, indent=2))
            raise SetupError("existing_docker_repository_ambiguous_select_from_private_inventory")
    repository_info = gc("artifacts", "repositories", "describe", registry, "--location", region, "--format=json(name,format)", json_output=True)
    if repository_info.get("format") != "DOCKER":
        raise SetupError("existing_artifact_repository_is_not_docker")
    github = command(["gh", "api", f"repos/{REPOSITORY}", "--jq", "{id:.id,owner_id:.owner.id}"], json_output=True)
    contract = provider_contract(number, str(github["id"]), str(github["owner_id"]))
    email = {role: f"{name}@{project}.iam.gserviceaccount.com" for role, name in ACCOUNTS.items()}
    scheduler_uri = f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job}:run"
    scheduler = gc("scheduler", "jobs", "describe", config["scheduler_job"], "--location", region, "--format=json", missing=True, json_output=True)
    scheduler_inventory = gc("scheduler", "jobs", "list", "--location", region, "--format=json(name,state,httpTarget.uri)", missing=True, json_output=True) or []
    other_triggers = [item["name"] for item in scheduler_inventory if item.get("state") == "ENABLED" and item.get("httpTarget", {}).get("uri") == scheduler_uri and item["name"].rsplit("/", 1)[-1] != config["scheduler_job"]]
    if scheduler and (scheduler.get("httpTarget", {}).get("uri") != scheduler_uri or scheduler.get("httpTarget", {}).get("oauthToken", {}).get("serviceAccountEmail") != email["scheduler"] or scheduler.get("schedule") != "0 4 * * 1" or scheduler.get("timeZone") != "Asia/Tokyo"):
        raise SetupError("existing_scheduler_configuration_conflicts")
    provider = gc("iam", "workload-identity-pools", "providers", "describe", PROVIDER, "--workload-identity-pool", POOL, "--location=global", "--format=json", missing=True, json_output=True)
    if provider and (provider.get("attributeMapping") != contract["attributeMapping"] or provider.get("attributeCondition") != contract["attributeCondition"] or provider.get("oidc", {}).get("issuerUri") != contract["issuerUri"] or provider.get("disabled") or provider.get("state") != "ACTIVE"):
        raise SetupError("existing_wif_provider_conflicts")
    secret_inventory = gc("secrets", "list", "--format=json(name)", json_output=True)
    # Use the already-authenticated gcloud operator in-memory. Cloud Shell need
    # not create ADC credentials or copy tokens through the chat.
    from google.cloud import storage
    from google.oauth2.credentials import Credentials
    from google.api_core.exceptions import NotFound
    from tatemono_map.cloud.storage import GCSStore, validate_head
    token = gc("auth", "print-access-token")
    store = GCSStore(bucket, client=storage.Client(project=project, credentials=Credentials(token)))
    try:
        existing_head, _ = store.read_head()
        validate_head(existing_head)
        needs_bootstrap = False
    except NotFound:
        needs_bootstrap = True
    gcs_candidates = [{"object": blob.name, "bytes": blob.size, "generation": int(blob.generation), "updated": blob.updated.isoformat() if blob.updated else None} for blob in store.bucket.list_blobs() if blob.name.endswith((".sqlite3", ".db"))]
    inventory = {"project": project_info, "bucket": bucket, "bucket_protection": {k: bucket_info.get(k) for k in ("uniform_bucket_level_access", "public_access_prevention", "versioning_enabled")}, "job": job_info, "artifact_repository": repository_info, "scheduler_present": bool(scheduler), "other_active_job_triggers": other_triggers, "wif_present": bool(provider), "secret_names": [row["name"] for row in secret_inventory], "gcs_database_candidates": gcs_candidates, "needs_bootstrap": needs_bootstrap}
    (args.output / "inventory.json").write_text(json.dumps(inventory, indent=2))
    plan = {
        "mode": "activate" if args.activate else "prepare_iam" if args.apply else "read_only",
        "existing_job_image": image,
        "rollback_service_account_act_as": previous_account if args.activate else None,
        "changes": ["enable identity/Secret/Storage APIs", "create missing runtime/deployer/publisher service accounts and WIF pool/provider", "bind existing enabled Ulucks login Secret to runtime only", "grant publisher read-only public/state access"],
        "activation_only": ["grant runtime storage writes and deployer Job/registry/actAs permissions", "enable bucket protection", "create collection Secret and paused Scheduler", "bootstrap reviewed master only if head missing", "set GitHub variables, enable cloud mode and dispatch reviewed main"],
        "job_impact": "No image/config update or execution in setup. GitHub cloud_deploy later adopts only the inspected image, retains existing environment and records the old Job spec privately before updating.",
        "permissions_required": ["read existing GCP assets and GitHub Actions variables", "Service Usage Admin", "Workload Identity Pool Admin", "Service Account Admin", "set IAM policy on selected bucket and Ulucks login Secret"] + (["Project IAM Admin (limited Scheduler role)", "Cloud Scheduler Admin", "Cloud Run Admin on existing Job", "Artifact Registry IAM", "GitHub Actions variable write and workflow dispatch"] if args.activate else []),
        "non_changes": ["no project/bucket/registry recreation", "no public bucket or SA key", "no RealPro secret access", "no website/template/URL/SEO changes"],
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    (args.output / "changes.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.apply:
        return
    # Preparation must remain harmless even if main is already cloud-enabled.
    # Do not create new deployer privileges that an existing workflow could use.
    variables = command(["gh", "variable", "list", "--repo", REPOSITORY, "--json", "name,value"], json_output=True)
    if not args.activate and any(v["name"] == "CLOUD_ENABLED" and v["value"] == "true" for v in variables):
        raise SetupError("cloud_already_enabled_review_before_iam_preparation")
    if other_triggers:
        raise SetupError("other_active_schedulers_target_existing_job_review_inventory")
    if args.activate and args.expected_job_image != image:
        raise SetupError("expected_job_image_does_not_match_inventory")
    # Validate private inputs before any write. Existing secret values are not read.
    secret_inputs = (("login_secret", args.login_file), ("collection_secret", args.collection_file)) if args.activate else (("login_secret", args.login_file),)
    for field, path in secret_inputs:
        existing = gc("secrets", "describe", config[field], "--format=json(name)", missing=True, json_output=True)
        if existing:
            versions = gc("secrets", "versions", "list", config[field], "--filter=state:ENABLED", "--limit=1", "--format=json(name)", json_output=True)
            if not versions:
                raise SetupError("existing_secret_has_no_enabled_version: " + field)
            if path:
                raise SetupError("existing_secret_is_reused_supply_no_file: " + field)
        elif not args.activate:
            raise SetupError("register_ulucks_login_in_console_before_preparation")
        elif not path or not path.is_file():
            raise SetupError("new_secret_requires_local_file: " + field)
        if path:
            value = json.loads(path.read_text())
            if field == "collection_secret":
                from tatemono_map.cloud.collector import validate_config
                validate_config(value)
            elif not value.get("username") or not value.get("password"):
                raise SetupError("login_json_incomplete")
    if args.activate:
        from tatemono_map.cloud.pipeline import validate_master
        from tatemono_map.cloud.public_db import sha256
        if not args.master or not args.master_sha256 or sha256(args.master) != args.master_sha256:
            raise SetupError("first_bootstrap_requires_verified_private_master_and_sha256")
        validate_master(args.master)
        if Path(str(args.master) + "-wal").exists():
            raise SetupError("close_and_checkpoint_master_before_transfer")
        if not needs_bootstrap and existing_head["master"]["sha256"] != args.master_sha256:
            raise SetupError("reviewed_master_does_not_match_existing_head")
    gc("services", "enable", *(APIS if args.activate else ("iam.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com", "secretmanager.googleapis.com", "storage.googleapis.com")))
    for role, name in ACCOUNTS.items():
        if role == "scheduler" and not args.activate:
            continue
        if gc("iam", "service-accounts", "describe", email[role], "--format=json(email)", missing=True, json_output=True) is None:
            gc("iam", "service-accounts", "create", name, "--display-name", f"Tatemono {role}")
    pool = gc("iam", "workload-identity-pools", "describe", POOL, "--location=global", "--format=json", missing=True, json_output=True)
    if pool is None:
        gc("iam", "workload-identity-pools", "create", POOL, "--location=global", "--display-name=Tatemono GitHub main")
    elif pool.get("state") != "ACTIVE" or pool.get("disabled"):
        raise SetupError("existing_wif_pool_not_active")
    if provider is None:
        # gcloud dictionary delimiter avoids commas inside CEL expressions.
        mapping = "^~^" + "~".join(f"{k}={v}" for k, v in contract["attributeMapping"].items())
        gc("iam", "workload-identity-pools", "providers", "create-oidc", PROVIDER, "--workload-identity-pool", POOL, "--location=global", "--issuer-uri", contract["issuerUri"], "--attribute-mapping", mapping, "--attribute-condition", contract["attributeCondition"])
    for role in ("deployer", "publisher"):
        principal = f"principalSet://iam.googleapis.com/projects/{number}/locations/global/workloadIdentityPools/{POOL}/attribute.role/{role}"
        gc("iam", "service-accounts", "add-iam-policy-binding", email[role], "--member", principal, "--role=roles/iam.workloadIdentityUser")
    prefix = f"projects/_/buckets/{bucket}/objects/"
    runtime_condition = "expression=" + " || ".join(f"resource.name.startsWith('{prefix}{path}')" for path in ("masters/", "backups/", "private-runs/", "public/", "state/")) + ",title=tatemono-cloud-runtime"
    public_condition = f"expression=resource.name == '{prefix}state/current.json' || resource.name.startsWith('{prefix}public/'),title=tatemono-public-reader"
    gc("storage", "buckets", "add-iam-policy-binding", "gs://" + bucket, "--member=serviceAccount:" + email["publisher"], "--role=roles/storage.objectViewer", "--condition", public_condition)
    if not args.activate:
        gc("secrets", "add-iam-policy-binding", config["login_secret"], "--member=serviceAccount:" + email["runtime"], "--role=roles/secretmanager.secretAccessor")
        print("IAM prepared only. No master/public write, Job change/run, Scheduler change, GitHub variable change or dispatch. Existing Secret values were not read.")
        return
    gc("storage", "buckets", "add-iam-policy-binding", "gs://" + bucket, "--member=serviceAccount:" + email["runtime"], "--role=roles/storage.objectAdmin", "--condition", runtime_condition)
    gc("storage", "buckets", "add-iam-policy-binding", "gs://" + bucket, "--member=serviceAccount:" + email["deployer"], "--role=roles/storage.objectCreator", "--condition", f"expression=resource.name.startsWith('{prefix}deployment-backups/'),title=tatemono-job-config-backup")
    gc("storage", "buckets", "update", "gs://" + bucket, "--versioning", "--public-access-prevention")
    for field, path in (("login_secret", args.login_file), ("collection_secret", args.collection_file)):
        if gc("secrets", "describe", config[field], "--format=json(name)", missing=True, json_output=True) is None:
            gc("secrets", "create", config[field], "--replication-policy=automatic")
            gc("secrets", "versions", "add", config[field], "--data-file", str(path))
        gc("secrets", "add-iam-policy-binding", config[field], "--member=serviceAccount:" + email["runtime"], "--role=roles/secretmanager.secretAccessor")
    gc("run", "jobs", "add-iam-policy-binding", job, "--region", region, "--member=serviceAccount:" + email["deployer"], "--role=roles/run.developer")
    gc("run", "jobs", "add-iam-policy-binding", job, "--region", region, "--member=serviceAccount:" + email["scheduler"], "--role=roles/run.invoker")
    gc("iam", "service-accounts", "add-iam-policy-binding", email["runtime"], "--member=serviceAccount:" + email["deployer"], "--role=roles/iam.serviceAccountUser")
    if previous_account != email["runtime"]:
        # Replacing the previous Job spec on a failed first adoption requires
        # actAs on that spec's original identity too. Explicitly show this
        # permission in the pre-apply plan; never grant it to the collector.
        gc("iam", "service-accounts", "add-iam-policy-binding", previous_account, "--member=serviceAccount:" + email["deployer"], "--role=roles/iam.serviceAccountUser")
    gc("artifacts", "repositories", "add-iam-policy-binding", registry, "--location", region, "--member=serviceAccount:" + email["deployer"], "--role=roles/artifactregistry.writer")
    # Scheduler has project-level IAM and does not support resource.name
    # conditions. Grant exactly get+enable (not update/create/run/admin), and
    # restrict the actual command to the configured job in deploy_job.py.
    custom_role = "tatemonoSchedulerEnable"
    role_info = gc("iam", "roles", "describe", custom_role, "--format=json(includedPermissions)", missing=True, json_output=True)
    permissions = ["cloudscheduler.jobs.get", "cloudscheduler.jobs.enable"]
    if role_info is None:
        gc("iam", "roles", "create", custom_role, "--title=Tatemono Scheduler enable", "--permissions", ",".join(permissions), "--stage=GA")
    elif set(role_info["includedPermissions"]) != set(permissions):
        raise SetupError("existing_scheduler_role_conflicts")
    gc("projects", "add-iam-policy-binding", project, "--member=serviceAccount:" + email["deployer"], "--role", f"projects/{project}/roles/{custom_role}", "--condition=None")
    if scheduler is None:
        # The job is created and immediately paused, before cloud mode is enabled.
        # Schedule is weekly; default retries disabled to avoid duplicate collection.
        future = datetime.now(timezone.utc) + timedelta(days=2)
        gc("scheduler", "jobs", "create", "http", config["scheduler_job"], "--location", region, f"--schedule=0 0 {future.day} {future.month} *", "--time-zone=Asia/Tokyo", "--uri", scheduler_uri, "--http-method=POST", "--oauth-service-account-email", email["scheduler"], "--oauth-token-scope=https://www.googleapis.com/auth/cloud-platform", "--message-body={}", "--max-retry-attempts=0")
        gc("scheduler", "jobs", "pause", config["scheduler_job"], "--location", region)
        gc("scheduler", "jobs", "update", "http", config["scheduler_job"], "--location", region, "--schedule=0 4 * * 1")
    if needs_bootstrap:
        from tatemono_map.cloud.run import bootstrap
        with tempfile.TemporaryDirectory(prefix="tatemono-bootstrap-", dir=args.output) as directory:
            bootstrap(store, args.master, args.master_sha256, Path(directory), command(["git", "rev-parse", "HEAD"]))
    variables = {
        "GCP_PROJECT_ID": project, "GCP_REGION": region, "GCP_BUCKET": bucket, "GCP_JOB": job,
        "GCP_ARTIFACT_REPOSITORY": registry, "GCP_SCHEDULER_JOB": config["scheduler_job"], "GCP_ADOPT_IMAGE": image,
        "GCP_WIF_PROVIDER": f"projects/{number}/locations/global/workloadIdentityPools/{POOL}/providers/{PROVIDER}",
        "GCP_DEPLOY_SERVICE_ACCOUNT": email["deployer"], "GCP_PAGES_SERVICE_ACCOUNT": email["publisher"], "GCP_RUNTIME_SERVICE_ACCOUNT": email["runtime"],
        "ULUCKS_CONFIG_SECRET": f"projects/{project}/secrets/{config['collection_secret']}/versions/latest",
        "ULUCKS_LOGIN_SECRET": f"projects/{project}/secrets/{config['login_secret']}/versions/latest",
    }
    for name, value in variables.items():
        command(["gh", "variable", "set", name, "--repo", REPOSITORY, "--body", value])
    command(["gh", "variable", "set", "CLOUD_ENABLED", "--repo", REPOSITORY, "--body", "true"])
    command(["gh", "workflow", "run", "cloud_deploy.yml", "--repo", REPOSITORY, "--ref", "main"])
    print("Setup complete. GitHub deployment dispatched. Scheduler stays paused until successful collection; GitHub reports production verification separately. Subsequent code pushes deploy automatically.")


if __name__ == "__main__":
    try:
        main()
    except (SetupError, KeyError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
