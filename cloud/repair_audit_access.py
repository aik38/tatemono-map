#!/usr/bin/env python3
"""One-time GCP-admin repair for the isolated read-only weekly audit identity.

Run from the repository root in an authenticated GCP admin environment:
  python cloud/repair_audit_access.py

This operation changes only the WIF provider allowlist, creates/binds the auditor
service account, grants read-only Cloud Run/Scheduler roles, and sets one GitHub
Actions variable. It does not run Jobs or alter Scheduler state, GCS data, SQLite,
GitHub Pages, or production collection configuration.
"""
from __future__ import annotations

import json

from setup_gcp import ACCOUNTS, POOL, PROVIDER, REPOSITORY, SetupError, command, provider_contract

PROJECT = "tatemono-map"


def gc(*args: str, missing: bool = False, json_output: bool = False):
    command_args = ["gcloud", *args, "--project", PROJECT, "--quiet"]
    if json_output:
        command_args.append("--format=json")
    return command(command_args, missing=missing, json_output=json_output)


def main() -> None:
    project = gc("projects", "describe", PROJECT, json_output=True)
    number = str(project["projectNumber"])
    repo = command(["gh", "api", f"repos/{REPOSITORY}", "--jq", "{id:.id,owner_id:.owner.id}"], json_output=True)
    expected = provider_contract(number, str(repo["id"]), str(repo["owner_id"]))
    provider = gc("iam", "workload-identity-pools", "providers", "describe", PROVIDER,
                  "--workload-identity-pool", POOL, "--location=global", json_output=True)
    if provider.get("state") != "ACTIVE" or provider.get("disabled"):
        raise SetupError("existing_wif_provider_not_active")
    if provider.get("oidc", {}).get("issuerUri") != expected["issuerUri"]:
        raise SetupError("existing_wif_issuer_mismatch")

    old_workflows = [f"{REPOSITORY}/.github/workflows/{name}@refs/heads/main"
                     for name in ("cloud_deploy.yml", "deploy_pages.yml")]
    old_mapping = {
        "google.subject": "assertion.sub",
        "attribute.repository_id": "assertion.repository_id",
        "attribute.role": f"assertion.workflow_ref == '{old_workflows[0]}' ? 'deployer' : 'publisher'",
    }
    old_condition = (
        f"assertion.repository_id == '{repo['id']}' && "
        f"assertion.repository_owner_id == '{repo['owner_id']}' && "
        f"assertion.repository == '{REPOSITORY}' && assertion.ref == 'refs/heads/main' && "
        f"assertion.workflow_ref in {json.dumps(old_workflows)}"
    )
    current_mapping = provider.get("attributeMapping")
    current_condition = provider.get("attributeCondition")
    already_repaired = current_mapping == expected["attributeMapping"] and current_condition == expected["attributeCondition"]
    if not already_repaired and (current_mapping != old_mapping or current_condition != old_condition):
        raise SetupError("unrecognized_existing_wif_contract_refusing_overwrite")

    auditor_name = ACCOUNTS["auditor"]
    auditor_email = f"{auditor_name}@{PROJECT}.iam.gserviceaccount.com"
    account = gc("iam", "service-accounts", "describe", auditor_email, missing=True, json_output=True)
    if account is None:
        gc("iam", "service-accounts", "create", auditor_name, "--display-name", "Tatemono read-only weekly auditor")

    if not already_repaired:
        mapping = "^~^" + "~".join(f"{key}={value}" for key, value in expected["attributeMapping"].items())
        gc("iam", "workload-identity-pools", "providers", "update-oidc", PROVIDER,
           "--workload-identity-pool", POOL, "--location=global",
           "--issuer-uri", expected["issuerUri"], "--attribute-mapping", mapping,
           "--attribute-condition", expected["attributeCondition"])

    principal = (f"principalSet://iam.googleapis.com/projects/{number}/locations/global/"
                 f"workloadIdentityPools/{POOL}/attribute.role/auditor")
    gc("iam", "service-accounts", "add-iam-policy-binding", auditor_email,
       "--member", principal, "--role=roles/iam.workloadIdentityUser")
    gc("projects", "add-iam-policy-binding", PROJECT,
       "--member=serviceAccount:" + auditor_email, "--role=roles/run.viewer")
    gc("projects", "add-iam-policy-binding", PROJECT,
       "--member=serviceAccount:" + auditor_email, "--role=roles/cloudscheduler.viewer")
    command(["gh", "variable", "set", "GCP_AUDIT_SERVICE_ACCOUNT",
             "--repo", REPOSITORY, "--body", auditor_email])

    verified = gc("iam", "workload-identity-pools", "providers", "describe", PROVIDER,
                  "--workload-identity-pool", POOL, "--location=global", json_output=True)
    if verified.get("attributeMapping") != expected["attributeMapping"] or verified.get("attributeCondition") != expected["attributeCondition"]:
        raise SetupError("wif_update_verification_failed")
    print(json.dumps({
        "result": "audit_identity_repaired",
        "service_account": auditor_email,
        "roles": ["roles/run.viewer", "roles/cloudscheduler.viewer"],
        "workflow": f"{REPOSITORY}/.github/workflows/weekly_cloud_run_audit.yml@refs/heads/main",
        "production_jobs_or_data_changed": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()