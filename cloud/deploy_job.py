#!/usr/bin/env python3
"""GitHub main only: back up Job config privately, update, collect, then resume."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def main():
    env = os.environ
    for key in ("GCP_PROJECT_ID", "GCP_REGION", "GCP_JOB", "GCP_BUCKET", "GCP_ADOPT_IMAGE", "GCP_RUNTIME_SERVICE_ACCOUNT", "GCP_SCHEDULER_JOB", "ULUCKS_CONFIG_SECRET", "ULUCKS_LOGIN_SECRET", "GITHUB_SHA", "COLLECTOR_IMAGE"):
        if not env.get(key):
            raise SystemExit("missing deployment setting: " + key)
    if env.get("GITHUB_REF") != "refs/heads/main" or env.get("GITHUB_REPOSITORY") != "aik38/tatemono-map":
        raise SystemExit("deployment is restricted to repository main")
    project, region, job = (env[k] for k in ("GCP_PROJECT_ID", "GCP_REGION", "GCP_JOB"))
    def gc(*args):
        result = subprocess.run(["gcloud", *args, "--project", project, "--quiet"], text=True, capture_output=True)
        if result.returncode:
            raise SystemExit("GCP deployment operation failed: " + " ".join(args[:3]))
        return result.stdout.strip()
    image = gc("run", "jobs", "describe", job, "--region", region, "--format=value(spec.template.spec.template.spec.containers[0].image)")
    managed = gc("run", "jobs", "describe", job, "--region", region, "--format=value(metadata.labels.managed-by)")
    if managed != "tatemono-cloud" and image != env["GCP_ADOPT_IMAGE"]:
        raise SystemExit("existing Job image changed since initial inspection; refusing overwrite")
    # Full prior configuration stays in GCS; it may contain private env settings.
    snapshot = Path("work/previous-job.yaml")
    snapshot.parent.mkdir(exist_ok=True)
    snapshot.write_text(gc("run", "jobs", "describe", job, "--region", region, "--format=export"))
    name = f"gs://{env['GCP_BUCKET']}/deployment-backups/{env['GITHUB_SHA']}-{env['GITHUB_RUN_ID']}-{env.get('GITHUB_RUN_ATTEMPT', '1')}.yaml"
    gc("storage", "cp", str(snapshot), name, "--if-generation-match=0")
    variables = {
        "TATEMONO_BUCKET": env["GCP_BUCKET"], "TATEMONO_SOURCE_COMMIT": env["GITHUB_SHA"],
        "ULUCKS_CONFIG_SECRET": env["ULUCKS_CONFIG_SECRET"], "ULUCKS_LOGIN_SECRET": env["ULUCKS_LOGIN_SECRET"],
    }
    gc("run", "jobs", "update", job, "--region", region, "--image", env["COLLECTOR_IMAGE"],
       "--service-account", env["GCP_RUNTIME_SERVICE_ACCOUNT"], "--command=python", "--args=-m,tatemono_map.cloud.run",
       "--tasks=1", "--parallelism=1", "--max-retries=0", "--task-timeout=3600s", "--memory=2Gi", "--cpu=1",
       "--update-env-vars", ",".join(f"{k}={v}" for k, v in variables.items()),
       "--update-labels", f"managed-by=tatemono-cloud,source-commit={env['GITHUB_SHA']}")
    generation = gc("run", "jobs", "describe", job, "--region", region, "--format=value(metadata.generation)")
    try:
        gc("run", "jobs", "execute", job, "--region", region, "--wait")
    except SystemExit:
        actual_generation = gc("run", "jobs", "describe", job, "--region", region, "--format=value(metadata.generation)")
        if actual_generation != generation:
            raise SystemExit("collection failed and Job changed concurrently; private backup retained, automatic rollback refused") from None
        gc("run", "jobs", "replace", str(snapshot), "--region", region)
        raise SystemExit("collection failed; previous Job configuration restored; public release unchanged") from None
    finally:
        snapshot.unlink(missing_ok=True)
    state = gc("scheduler", "jobs", "describe", env["GCP_SCHEDULER_JOB"], "--location", region, "--format=value(state)")
    if state == "PAUSED":
        gc("scheduler", "jobs", "resume", env["GCP_SCHEDULER_JOB"], "--location", region)
    elif state != "ENABLED":
        raise SystemExit("unexpected Scheduler state; inspect existing job")
    print("Collection committed successfully; weekly Scheduler enabled. Pages must verify the public release separately.")


if __name__ == "__main__":
    main()
