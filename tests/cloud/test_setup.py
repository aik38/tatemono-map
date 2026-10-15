from __future__ import annotations

import importlib.util
import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "cloud" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeCloud:
    def __init__(self):
        self.calls = []
        self.provider = None
        self.pool = None
        self.scheduler = None
        self.accounts = set()
        self.role = None
        self.variables = []
        # Synthetic Storage JSON API response, not gcloud display aliases.
        # https://github.com/googleapis/google-api-go-client/blob/main/storage/v1/storage-api.json
        self.bucket = json.loads((ROOT / "tests/cloud/fixtures/gcloud_bucket_raw.json").read_text())
        self.contract = module("setup_gcp").provider_contract("123", "456", "789")

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        words = " ".join(argv)
        if argv[0] == "gh":
            if argv[1:3] == ["variable", "list"]:
                return self.variables
            if argv[-1] == ".object.sha":
                return "a" * 40
            return {"id": 456, "owner_id": 789} if "--jq" in argv and argv[-1].startswith("{id") else "ok"
        if "projects describe" in words:
            return {"projectId": "tatemono-map", "projectNumber": "123"}
        if "buckets describe" in words:
            assert "--raw" in argv and "--format=json" in argv
            return copy.deepcopy(self.bucket)
        if "buckets get-iam-policy" in words:
            return {"bindings": []}
        if "jobs describe" in words and "scheduler" not in words:
            return {"apiVersion": "run.googleapis.com/v1", "kind": "Job", "metadata": {"name": "tatemono-collection-poc"}, "spec": {"template": {"spec": {"template": {"spec": {"containers": [{"image": "approved-image"}], "serviceAccountName": "existing-job@tatemono-map.iam.gserviceaccount.com"}}}}}}
        if "repositories describe" in words:
            return {"name": "registry", "format": "DOCKER"}
        if "repositories list" in words:
            return [{"name": "projects/tatemono-map/locations/asia-northeast1/repositories/existing-registry", "format": "DOCKER"}]
        if "providers describe" in words:
            return self.provider
        if "providers create-oidc" in words:
            self.provider = {"attributeMapping": self.contract["attributeMapping"], "attributeCondition": self.contract["attributeCondition"], "oidc": {"issuerUri": self.contract["issuerUri"]}, "state": "ACTIVE"}
        if "workload-identity-pools describe" in words:
            return self.pool
        if "workload-identity-pools create" in words:
            self.pool = {"state": "ACTIVE"}
        if "service-accounts describe" in words:
            return {} if argv[4] in self.accounts else None
        if "service-accounts create" in words:
            self.accounts.add(argv[4] + "@tatemono-map.iam.gserviceaccount.com")
        if "scheduler jobs describe" in words:
            return self.scheduler
        if "scheduler jobs create" in words:
            self.scheduler = {"httpTarget": {"uri": "https://run.googleapis.com/v2/projects/tatemono-map/locations/asia-northeast1/jobs/tatemono-collection-poc:run", "oauthToken": {"serviceAccountEmail": "tm-weekly-trigger@tatemono-map.iam.gserviceaccount.com"}}, "schedule": "0 4 * * 1", "timeZone": "Asia/Tokyo"}
        if "iam roles describe" in words:
            return self.role
        if "iam roles create" in words:
            self.role = {"includedPermissions": ["cloudscheduler.jobs.get", "cloudscheduler.jobs.enable"]}
        if "secrets list" in words:
            return [{"name": "tm-poc-realpro-login"}, {"name": "tm-poc-gmail-token"}, {"name": "tm-ulucks-login"}, {"name": "tm-ulucks-config"}]
        if "secrets describe" in words:
            return {"name": argv[3]}
        if "secrets versions list" in words:
            return [{"name": "version1"}]
        if "auth print-access-token" in words:
            return "fake-in-memory-token"
        if "rev-parse" in words:
            return "a" * 40
        return ""


@pytest.mark.parametrize("head_present", [True, False])
@pytest.mark.parametrize("project_number_type", [str, int])
def test_setup_is_read_only_by_default_then_prepares_iam_without_production_permissions(tmp_path, monkeypatch, master, head_present, project_number_type):
    mod = module("setup_gcp")
    config = tmp_path / "config.json"
    settings = json.loads((ROOT / "cloud/setup.example.json").read_text())
    config.write_text(json.dumps(settings))
    fake = FakeCloud()
    fake.bucket["projectNumber"] = project_number_type(123)
    class Bucket:
        def list_blobs(self):
            return []
    class Store:
        bucket = Bucket()
        def __init__(self, *_args, **_kw):
            pass
        def read_head(self):
            if not head_present:
                from google.api_core.exceptions import NotFound
                raise NotFound("no initial master")
            from tatemono_map.cloud.public_db import sha256
            return {"schema": 1, "qc": "passed", "run_id": "20261016T000000Z-000000000000", "master": {"object": "masters/20261016T000000Z-000000000000.sqlite3", "sha256": sha256(master), "generation": 1}, "public": {"object": "public/releases/20261016T000000Z-000000000000/public.sqlite3", "sha256": "b" * 64, "generation": 2}}, 1
    monkeypatch.setattr(mod, "command", fake)
    monkeypatch.setattr("tatemono_map.cloud.storage.GCSStore", Store)
    args = ["setup_gcp.py", "--config", str(config), "--output", str(tmp_path / "inventory")]
    monkeypatch.setattr(sys, "argv", args)
    mod.main()
    inventory = json.loads((tmp_path / "inventory/inventory.json").read_text())
    assert inventory["bucket_protection"] == {
        "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}, "publicAccessPrevention": "enforced"},
        "versioning": {"enabled": True},
    }
    assert inventory["job"]["spec"]["template"]["spec"]["template"]["spec"]["serviceAccountName"] == "existing-job@tatemono-map.iam.gserviceaccount.com"
    assert not any(word in ("create", "create-oidc", "update", "set", "add-iam-policy-binding", "enable", "pause", "execute") for call in fake.calls for word in call)
    for _ in range(2):
        monkeypatch.setattr(sys, "argv", args + ["--apply", "--expected-job-image", "approved-image"])
        mod.main()
    calls = [" ".join(call) for call in fake.calls]
    assert sum("providers create-oidc" in call for call in calls) == 1
    assert not any("scheduler jobs create" in call or "workflow run" in call or "variable set" in call or "storage.objectAdmin" in call or "run.developer" in call or "artifactregistry.writer" in call or "serviceAccountUser" in call for call in calls)
    assert not any("secrets versions add" in call or "secrets delete" in call or "keys create" in call for call in calls)
    mutations = [call for call in calls if "add-iam-policy-binding" in call]
    assert all("tm-poc-realpro-login" not in call and "tm-poc-gmail-token" not in call for call in mutations)
    assert not any("run jobs update" in call or "run jobs execute" in call for call in calls)
    assert any("attribute.role/deployer" in call for call in mutations)
    assert any("attribute.role/publisher" in call for call in mutations)
    # Storage omits versioning when it has never been configured. Do not report
    # unknown display aliases as None or mistake missing versioning for enabled.
    monkeypatch.setattr(sys, "argv", args)
    for enabled in (False, None):
        if enabled is None:
            fake.bucket.pop("versioning")
        else:
            fake.bucket["versioning"] = {"enabled": enabled}
        fake.bucket["iamConfiguration"]["publicAccessPrevention"] = "inherited"
        mod.main()
        protection = json.loads((tmp_path / "inventory/inventory.json").read_text())["bucket_protection"]
        assert protection["versioning"] == {"enabled": False}
        assert protection["iamConfiguration"]["publicAccessPrevention"] == "inherited"
    fake.variables = [{"name": "CLOUD_ENABLED", "value": "true"}]
    before = len(fake.calls)
    monkeypatch.setattr(sys, "argv", args + ["--apply"])
    with pytest.raises(mod.SetupError, match="cloud_already_enabled"):
        mod.main()
    assert not any(word in ("create", "enable", "add-iam-policy-binding", "update", "set") for call in fake.calls[before:] for word in call)
    fake.variables = []
    before = len(fake.calls)
    monkeypatch.setattr(sys, "argv", args + ["--apply", "--activate", "--expected-job-image", "approved-image", "--reviewed-commit", "a" * 40])
    with pytest.raises(mod.SetupError, match="requires_verified_private_master"):
        mod.main()
    assert not any(word in ("create", "enable", "add-iam-policy-binding", "update", "set") for call in fake.calls[before:] for word in call)
    if not head_present:
        # Preparation succeeds without a master and without any upload method.
        return
    # Activation is a separate, explicit reviewed-main + reviewed-master gate.
    from tatemono_map.cloud.public_db import sha256
    monkeypatch.setattr(sys, "argv", args + ["--apply", "--activate", "--expected-job-image", "approved-image", "--reviewed-commit", "a" * 40, "--master", str(master), "--master-sha256", sha256(master)])
    mod.main()
    calls = [" ".join(call) for call in fake.calls]
    assert sum("scheduler jobs create" in call for call in calls) == 1
    assert any("workflow run" in call for call in calls)
    assert not any("secrets versions access" in call for call in calls)
    assert json.loads((tmp_path / "inventory/changes.json").read_text())["rollback_service_account_act_as"] == "existing-job@tatemono-map.iam.gserviceaccount.com"


@pytest.mark.parametrize("change,expected_error", [
    ({"projectNumber": "999"}, "bucket_project_mismatch"),
    ({"projectNumber": None, "project_number": "123"}, "bucket_project_mismatch"),
    ({"iamConfiguration": {}}, "bucket_requires_uniform_access_review"),
    ({"iamConfiguration": {"uniformBucketLevelAccess": {"enabled": False}}}, "bucket_requires_uniform_access_review"),
    ({"iamConfiguration": {"uniformBucketLevelAccess": {"enabled": "true"}}}, "bucket_requires_uniform_access_review"),
    ({"acl": [{"entity": "allUsers", "role": "READER"}]}, "bucket_has_public_acl"),
    ({"defaultObjectAcl": [{"entity": "allAuthenticatedUsers", "role": "READER"}]}, "bucket_has_public_acl"),
])
def test_raw_bucket_safety_checks_reject_mismatch_or_public_access_before_mutations(tmp_path, monkeypatch, change, expected_error):
    mod = module("setup_gcp")
    config = tmp_path / "config.json"
    config.write_text((ROOT / "cloud/setup.example.json").read_text())
    fake = FakeCloud()
    fake.bucket.update(change)
    monkeypatch.setattr(mod, "command", fake)
    monkeypatch.setattr(sys, "argv", ["setup_gcp.py", "--config", str(config), "--apply", "--output", str(tmp_path / "inventory")])
    with pytest.raises(mod.SetupError, match=expected_error):
        mod.main()
    assert not any(word in ("create", "enable", "add-iam-policy-binding", "update", "set", "execute") for call in fake.calls for word in call)


@pytest.mark.parametrize("options", [["--activate"], ["--apply", "--activate"], ["--apply", "--activate", "--reviewed-commit", "b" * 40]])
def test_activation_without_reviewed_main_is_blocked_before_cloud_mutations(tmp_path, monkeypatch, options):
    mod = module("setup_gcp")
    fake = FakeCloud()
    monkeypatch.setattr(mod, "command", fake)
    monkeypatch.setattr(sys, "argv", ["setup_gcp.py", "--config", str(tmp_path / "not-read.json"), *options])
    with pytest.raises(mod.SetupError, match="activation_requires"):
        mod.main()
    assert not any(c[0] == "gcloud" for c in fake.calls)


def test_setup_refuses_binding_realpro_secret(tmp_path, monkeypatch):
    mod = module("setup_gcp")
    settings = json.loads((ROOT / "cloud/setup.example.json").read_text())
    settings["login_secret"] = "tm-poc-realpro-login"
    config = tmp_path / "bad.json"
    config.write_text(json.dumps(settings))
    monkeypatch.setattr(sys, "argv", ["setup_gcp.py", "--config", str(config)])
    with pytest.raises(mod.SetupError, match="only_dedicated"):
        mod.main()
