#!/usr/bin/env python3
"""Read-only first connection: asset metadata and generation-pinned DB audit.

No Secret payload access, IAM mutation, Job execution, upload or publication.
All reports and downloaded candidates stay private under work/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from audit_master import audit, read_keys

PROJECT = "tatemono-map"
REGION = "asia-northeast1"
MAX_OBJECT_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


def command(argv):
    result = subprocess.run(argv, text=True, capture_output=True)
    if result.returncode:
        # Neither stdout nor stderr (which may contain private configuration)
        # leaves the subprocess on failure. Permission/API failures are explicit.
        raise RuntimeError("read_failed: " + " ".join(argv[:4]))
    return json.loads(result.stdout) if result.stdout.strip() else None


def inventory(client, output, roots, canonical=None, aliases=None, *, reader=command):
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    report = {"project": PROJECT, "region": REGION, "mode": "read_only", "auto_selected": False,
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "errors": [], "assets": {}, "buckets": [], "candidates": [], "local_code_fingerprints": []}

    def gc(key, *args):
        try:
            formatting = [] if any(arg.startswith("--format=") for arg in args) else ["--format=json"]
            value = reader(["gcloud", *args, "--project", PROJECT, "--quiet", *formatting])
            report["assets"][key] = value
            return value
        except RuntimeError:
            report["errors"].append(key + ": unreadable_or_api_disabled")
            return None

    gc("project", "projects", "describe", PROJECT, "--format=json(projectId,projectNumber)")
    gc("enabled_apis", "services", "list", "--enabled", "--format=json(config.name)")
    # Explicit projections exclude environment variables, headers and payloads.
    jobs = gc("jobs", "run", "jobs", "list", "--region", REGION,
       "--format=json(metadata.name,metadata.labels,spec.template.spec.template.spec.containers.image,spec.template.spec.template.spec.serviceAccountName)")
    for job in jobs or []:
        name = job["metadata"]["name"].rsplit("/", 1)[-1]
        gc("job_iam_" + name, "run", "jobs", "get-iam-policy", name, "--region", REGION)
        gc("executions_" + name, "run", "jobs", "executions", "list", "--job", name, "--region", REGION, "--limit=10", "--format=json(metadata.name,metadata.creationTimestamp,status.completionTime,status.succeededCount,status.failedCount)")
    registries = gc("registry", "artifacts", "repositories", "list", "--location", REGION, "--format=json(name,format)")
    for registry in registries or []:
        name = registry["name"].rsplit("/", 1)[-1]
        gc("registry_iam_" + name, "artifacts", "repositories", "get-iam-policy", name, "--location", REGION)
    gc("schedulers", "scheduler", "jobs", "list", "--location", REGION, "--format=json(name,state,schedule,timeZone,httpTarget.uri,httpTarget.oauthToken.serviceAccountEmail)")
    accounts = gc("service_accounts", "iam", "service-accounts", "list", "--format=json(email,disabled)")
    for account in accounts or []:
        gc("service_account_iam_" + account["email"], "iam", "service-accounts", "get-iam-policy", account["email"])
    gc("project_iam", "projects", "get-iam-policy", PROJECT)
    pools = gc("wif_pools", "iam", "workload-identity-pools", "list", "--location=global")
    for pool in pools or []:
        name = pool["name"].rsplit("/", 1)[-1]
        gc("wif_providers_" + name, "iam", "workload-identity-pools", "providers", "list", "--workload-identity-pool", name, "--location=global")
    gc("secret_names", "secrets", "list", "--format=json(name)")
    gc("ulucks_versions", "secrets", "versions", "list", "tm-ulucks-login", "--format=json(name,state,createTime)")
    gc("ulucks_iam", "secrets", "get-iam-policy", "tm-ulucks-login")
    # Metadata only. Never use `secrets versions access` or read other Secrets.
    total = 0
    try:
        buckets = list(client.list_buckets(project=PROJECT))
    except Exception:
        buckets = []
        report["errors"].append("buckets: unreadable")
    for bucket in buckets:
        info = {"name": bucket.name, "candidates": 0}
        report["buckets"].append(info)
        gc("bucket_" + bucket.name, "storage", "buckets", "describe", "gs://" + bucket.name, "--raw", "--format=json")
        gc("bucket_iam_" + bucket.name, "storage", "buckets", "get-iam-policy", "gs://" + bucket.name)
        sidecars = set()
        bucket_candidates = []
        try:
            # Include backup generations, including non-current versions.
            for blob in bucket.list_blobs(versions=True):
                if blob.name.lower().endswith(("-wal", "-journal")) and blob.size:
                    sidecars.add(blob.name.rsplit("-", 1)[0])
                if not blob.name.lower().endswith((".sqlite3", ".sqlite", ".db")):
                    continue
                generation = int(blob.generation)
                item = {"origin": "gcs", "bucket": bucket.name, "object": blob.name,
                        "generation": generation, "bytes": blob.size,
                        "updated": blob.updated.isoformat() if blob.updated else None,
                        "candidate": False}
                report["candidates"].append(item)
                bucket_candidates.append(item)
                info["candidates"] += 1
                if not blob.size or blob.size > MAX_OBJECT_BYTES or total + blob.size > MAX_TOTAL_BYTES:
                    item["decision"] = "not_downloaded_size_budget_review_required"
                    continue
                total += blob.size
                # Never use an object name as a local filesystem path.
                filename = hashlib.sha256(f"{bucket.name}/{blob.name}#{generation}".encode()).hexdigest() + ".sqlite3"
                local = output / "candidates" / filename
                local.parent.mkdir(mode=0o700, exist_ok=True)
                try:
                    blob.download_to_filename(str(local), if_generation_match=generation, checksum="auto")
                    item.update(audit(local, canonical, aliases))
                except Exception:
                    local.unlink(missing_ok=True)
                    item["decision"] = "generation_pinned_download_or_audit_failed"
                    report["errors"].append("candidate_unreadable")
        except Exception:
            report["errors"].append("bucket_objects_unreadable: " + bucket.name)
        for item in bucket_candidates:
            if item["object"] in sidecars:
                item["candidate"] = False
                item["decision"] = "cloud_sidecar_present_requires_standalone_snapshot_review"
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        for source in sorted(root.iterdir()):
            if source.is_file() and (source.suffix == ".py" or source.name == "Dockerfile"):
                from tatemono_map.cloud.public_db import sha256
                code_sha = sha256(source)
                report["local_code_fingerprints"].append({"path": str(source), "sha256": code_sha,
                    "matches_pr351_poc": code_sha == "f21359884a1ffde31cf400efb20940312e56cd4d534992fb16067f25b92991da"})
        for pattern in ("*.sqlite3", "*.sqlite", "*.db"):
            for path in root.rglob(pattern):
                path = path.resolve()
                if path in seen or output.resolve() in path.parents:
                    continue
                seen.add(path)
                try:
                    report["candidates"].append({"origin": "local", **audit(path, canonical, aliases)})
                except OSError:
                    report["errors"].append("local_candidate_unreadable")
    report["complete"] = not report["errors"] and not any("not_downloaded" in c.get("decision", "") for c in report["candidates"])
    report["master_status"] = "requires_windows_gcp_history_and_company_ownership_review"
    (output / "report.private.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("work/first-connect"))
    parser.add_argument("--root", type=Path, action="append", default=[])
    parser.add_argument("--canonical-csv", type=Path)
    parser.add_argument("--aliases-csv", type=Path)
    args = parser.parse_args()
    # Use the logged-in operator in-memory. No ADC file or SA key is created.
    from google.cloud import storage
    from google.oauth2.credentials import Credentials
    result = subprocess.run(["gcloud", "auth", "print-access-token", "--project", PROJECT, "--quiet"], text=True, capture_output=True)
    if result.returncode:
        raise SystemExit("gcloud_operator_authentication_required")
    client = storage.Client(project=PROJECT, credentials=Credentials(result.stdout.strip()))
    report = inventory(client, args.output, args.root, read_keys(args.canonical_csv, "building_key"), read_keys(args.aliases_csv, "canonical_building_key"))
    print(json.dumps({"report": str(args.output / "report.private.json"), "complete": report["complete"],
                      "candidates": len(report["candidates"]), "possible_masters": sum(bool(c.get("candidate")) for c in report["candidates"]),
                      "auto_selected": False, "production_updated": False}))
    if not report["complete"]:
        raise SystemExit("read_only_audit_incomplete_see_private_report")


if __name__ == "__main__":
    main()
