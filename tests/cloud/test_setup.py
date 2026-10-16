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
                return copy.deepcopy(self.variables)
            if argv[1:3] == ["variable", "set"]:
                value = argv[argv.index('--body') + 1]
                if not value:
                    raise RuntimeError('GitHub rejects empty variable values')
                self.variables = [v for v in self.variables if v['name'] != argv[3]]
                self.variables.append({'name': argv[3], 'value': value})
                return ''
            if argv[1:3] == ["variable", "delete"]:
                if not any(v['name'] == argv[3] for v in self.variables):
                    raise RuntimeError('variable not found')
                self.variables = [v for v in self.variables if v['name'] != argv[3]]
                return ''
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
            assert "--format=json" in argv
            assert not any(arg.startswith("--format=json(") for arg in argv)
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
            return {"email": argv[4]} if argv[4] in self.accounts else None
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

    # A completed IAM preparation is reused during the resumable activation;
    # neither WIF bindings nor publication-reader binding is rewritten.
    before = len(fake.calls)
    monkeypatch.setattr(sys, "argv", args + ["--apply", "--activate", "--prepared-iam", "--no-dispatch", "--expected-job-image", "approved-image", "--reviewed-commit", "a" * 40, "--master", str(master), "--master-sha256", sha256(master)])
    mod.main()
    new_calls = [" ".join(call) for call in fake.calls[before:]]
    assert not any("workflow run" in call or "attribute.role/" in call or "storage.objectViewer" in call or "providers create-oidc" in call for call in new_calls)


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


@pytest.mark.parametrize("error", ["SERVICE_DISABLED: API has not been used", "PERMISSION_DENIED"])
def test_disabled_api_or_permission_error_is_not_a_missing_resource(error):
    mod = module("setup_gcp")
    import subprocess
    with patch.object(mod.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", error)):
        with pytest.raises(mod.SetupError, match="command_failed"):
            mod.command(["gcloud", "scheduler", "jobs", "describe", "test"], missing=True, json_output=True)


@pytest.mark.parametrize("resource,error", [
    ({"spec": {"template": {"spec": {"template": {"spec": {"image": ["old-projected-image"]}}}}}}, "invalid_cloud_run"),
    ({"apiVersion": "run.googleapis.com/v1", "kind": "Job", "metadata": {"name": "job"}, "spec": {"template": {"spec": {"template": {"spec": {"containers": [{"image": "a"}, {"image": "b"}]}}}}}}, "exactly_one_container"),
])
def test_bad_or_multi_container_job_is_rejected_before_iam_changes(tmp_path, monkeypatch, resource, error):
    mod = module("setup_gcp")
    config = tmp_path / "config.json"
    config.write_text((ROOT / "cloud/setup.example.json").read_text())
    fake = FakeCloud()
    def command(argv, **kw):
        if argv[1:4] == ["run", "jobs", "describe"]:
            return resource
        return fake(argv, **kw)
    monkeypatch.setattr(mod, "command", command)
    monkeypatch.setattr(sys, "argv", ["setup_gcp.py", "--config", str(config), "--apply", "--output", str(tmp_path / "out")])
    with pytest.raises((ValueError, mod.SetupError), match=error):
        mod.main()
    assert not any(word in ("create", "enable", "add-iam-policy-binding", "update", "set") for call in fake.calls for word in call)


@pytest.mark.parametrize("target,response,error", [
    (["artifacts", "repositories", "describe"], {"format": "MAVEN"}, "not_docker"),
    (["iam", "workload-identity-pools", "providers", "describe"], {"state": "DELETED"}, "wif_provider_conflicts"),
    (["iam", "workload-identity-pools", "describe"], {"state": "DELETED"}, "wif_pool_not_active"),
    (["iam", "service-accounts", "describe"], {"email": "unexpected", "disabled": True}, "service_account_conflicts"),
    (["scheduler", "jobs", "describe"], {"httpTarget": {"uri": "unexpected"}}, "scheduler_configuration_conflicts"),
])
def test_conflicting_assets_stop_before_any_mutation(tmp_path, monkeypatch, target, response, error):
    mod = module("setup_gcp")
    config = tmp_path / "config.json"
    config.write_text((ROOT / "cloud/setup.example.json").read_text())
    fake = FakeCloud()
    def command(argv, **kw):
        if argv[1:1 + len(target)] == target:
            return response
        return fake(argv, **kw)
    monkeypatch.setattr(mod, "command", command)
    monkeypatch.setattr(sys, "argv", ["setup_gcp.py", "--config", str(config), "--apply", "--output", str(tmp_path / "out")])
    with pytest.raises(mod.SetupError, match=error):
        mod.main()
    assert not any(word in ("create", "enable", "add-iam-policy-binding", "update", "set") for call in fake.calls for word in call)


@pytest.mark.parametrize('stale_secret_variable', [False, True])
def test_prepared_activation_with_environment_contract_never_mutates_secrets(master, config, tmp_path, monkeypatch, stale_secret_variable):
    from tatemono_map.cloud.public_db import sha256
    mod = module('setup_gcp')
    fake = FakeCloud()
    if stale_secret_variable:
        fake.variables = [{'name': 'ULUCKS_CONFIG_SECRET', 'value': 'old-config-reference'}]
    fake.pool = {'state':'ACTIVE'}
    fake.provider = {**fake.contract,'state':'ACTIVE'}
    fake.provider['oidc'] = {'issuerUri':fake.contract['issuerUri']}
    fake.accounts = {name+'@tatemono-map.iam.gserviceaccount.com' for name in mod.ACCOUNTS.values()}
    class Store:
        def __init__(self,*a,**kw):
            from types import SimpleNamespace
            self.bucket = SimpleNamespace(list_blobs=lambda:[])
        def read_head(self):
            run='20261016T000000Z-000000000000'
            return {'schema':1,'qc':'passed','run_id':run,'master':{'object':f'masters/{run}.sqlite3','sha256':sha256(master),'generation':1},'public':{'object':f'public/releases/{run}/public.sqlite3','sha256':'b'*64,'generation':2}},1
    monkeypatch.setattr(mod,'command',fake)
    monkeypatch.setattr('tatemono_map.cloud.storage.GCSStore',Store)
    settings=tmp_path/'setup.json';settings.write_text((ROOT/'cloud/setup.example.json').read_text())
    contract=tmp_path/'collection.json';contract.write_text(json.dumps(config))
    monkeypatch.setattr(sys,'argv',['setup','--config',str(settings),'--apply','--activate','--prepared-iam','--no-dispatch','--collection-config-env','--collection-file',str(contract),'--reviewed-commit','a'*40,'--expected-job-image','approved-image','--master',str(master),'--master-sha256',sha256(master),'--output',str(tmp_path/'inventory')])
    mod.main()
    secret_calls=[call for call in fake.calls if call[:2]==['gcloud','secrets']]
    assert secret_calls
    assert all(call[2] in ('list','describe') or call[2:4]==['versions','list'] for call in secret_calls)
    assert not any('tm-ulucks-config' in call for call in secret_calls)
    variable=next(call for call in fake.calls if call[:4]==['gh','variable','set','ULUCKS_CONFIG_JSON'])
    assert json.loads(variable[-1]) == config
    assert not any(c[:4] == ['gh','variable','set','ULUCKS_CONFIG_SECRET'] for c in fake.calls)
    deletions = [c for c in fake.calls if c[:3] == ['gh','variable','delete']]
    assert len(deletions) == int(stale_secret_variable)
    if deletions:
        assert deletions[0][3] == 'ULUCKS_CONFIG_SECRET'
        assert fake.calls.index(variable) < fake.calls.index(deletions[0])
    assert fake.calls[-1][:4] == ['gh','variable','set','CLOUD_ENABLED']
    assert not any(call[1:3]==['workflow','run'] for call in fake.calls)


def test_bootstrap_timeout_resumes_across_a_reviewed_fix_without_enabling_cloud_early(master, config, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from google.api_core.exceptions import NotFound
    from conftest import MemoryStore
    from tatemono_map.cloud.public_db import sha256
    mod=module('setup_gcp');fake=FakeCloud();current='a'*40
    fake.pool={'state':'ACTIVE'}
    fake.provider={**fake.contract,'state':'ACTIVE','oidc':{'issuerUri':fake.contract['issuerUri']}}
    fake.accounts={name+'@tatemono-map.iam.gserviceaccount.com' for name in mod.ACCOUNTS.values()}
    class Store(MemoryStore):
        def read_head(self):
            if self.head is None:raise NotFound('not yet registered')
            return super().read_head()
    store=Store(tmp_path/'objects')
    store.bucket=SimpleNamespace(list_blobs=lambda:[SimpleNamespace(name=name,size=path.stat().st_size,generation=ref['generation'],updated=None) for name,(ref,path) in store.objects.items()])
    store.fail_upload_prefix='public/'
    def command(args,**kw):
        if args[:2]==['git','rev-parse'] or args[-1:]==['.object.sha']:return current
        return fake(args,**kw)
    monkeypatch.setattr(mod,'command',command)
    monkeypatch.setattr('tatemono_map.cloud.storage.GCSStore',lambda *a,**kw:store)
    settings=tmp_path/'setup.json';settings.write_text((ROOT/'cloud/setup.example.json').read_text())
    contract=tmp_path/'contract.json';contract.write_text(json.dumps(config))
    output=tmp_path/'setup-output'
    def args(extra=()):
        return ['setup','--config',str(settings),'--apply','--activate','--prepared-iam','--no-dispatch','--collection-config-env','--collection-file',str(contract),'--reviewed-commit',current,'--expected-job-image','approved-image','--master',str(master),'--master-sha256',sha256(master),'--output',str(output),*extra]
    monkeypatch.setattr(sys,'argv',args())
    with pytest.raises(RuntimeError,match='upload failure'):mod.main()
    assert len(store.objects)==1 and store.head is None
    progress=json.loads((output/'bootstrap/bootstrap-progress.private.json').read_text())
    assert progress['stage']=='public_upload'
    assert not any(c[:3]==['gh','variable','set'] for c in fake.calls)
    current='b'*40;store.fail_upload_prefix=None
    before=len(fake.calls)
    monkeypatch.setattr(sys,'argv',args())
    with pytest.raises(Exception,match='binding_changed'):mod.main()
    assert not any('add-iam-policy-binding' in c for c in fake.calls[before:])
    monkeypatch.setattr(sys,'argv',args(['--resume-bootstrap','--previous-reviewed-commit','a'*40]))
    mod.main()
    assert len(store.objects)==2 and store.head['run_id']==progress['run_id']
    assert store.head['source_commit']=='a'*40
    assert any(c[:4]==['gh','variable','set','CLOUD_ENABLED'] for c in fake.calls)
    assert not any(c[1:3]==['workflow','run'] for c in fake.calls)
    assert not any(c[:3] in (['gcloud','secrets','create'],['gcloud','secrets','add-iam-policy-binding']) for c in fake.calls)


@pytest.mark.parametrize('failure', [None, 'json', 'delete'])
def test_registered_bootstrap_resumes_variable_setup_without_regeneration_or_gcs_writes(master, config, tmp_path, monkeypatch, failure):
    from types import SimpleNamespace
    from conftest import MemoryStore
    from tatemono_map.cloud.bootstrap import prepare, register
    from tatemono_map.cloud.public_db import sha256
    mod = module('setup_gcp'); fake = FakeCloud()
    fake.pool = {'state': 'ACTIVE'}
    fake.provider = {**fake.contract, 'state': 'ACTIVE', 'oidc': {'issuerUri': fake.contract['issuerUri']}}
    fake.accounts = {name + '@tatemono-map.iam.gserviceaccount.com' for name in mod.ACCOUNTS.values()}
    fake.variables = [{'name': 'ULUCKS_CONFIG_SECRET', 'value': 'obsolete-reference'},
                      {'name': 'UNRELATED', 'value': 'preserve-me'}]
    settings = tmp_path / 'setup.json'; settings.write_text((ROOT / 'cloud/setup.example.json').read_text())
    bucket = json.loads(settings.read_text())['bucket']
    contract = tmp_path / 'contract.json'; contract.write_text(json.dumps(config))
    output = tmp_path / 'setup-output'; work = output / 'bootstrap'
    store = MemoryStore(tmp_path / 'objects')
    store.bucket = SimpleNamespace(list_blobs=lambda: [])
    state = prepare(master, sha256(master), work, 'b'*40, bucket=bucket)
    register(store, state, work)
    before_head, before_generation = store.read_head()
    before_files = {p: p.read_bytes() for p in work.iterdir()}
    before_objects = {name: (copy.deepcopy(ref), path.read_bytes()) for name, (ref, path) in store.objects.items()}
    def forbidden(*args, **kw):
        raise AssertionError('registered DBs must never be regenerated or written')
    for target in ('snapshot_sqlite', 'export_public', 'prepare', 'register'):
        monkeypatch.setattr('tatemono_map.cloud.bootstrap.' + target, forbidden)
    monkeypatch.setattr('tatemono_map.cloud.public_db.snapshot_sqlite', forbidden)
    for target in ('upload', 'upload_verified', 'commit'):
        monkeypatch.setattr(store, target, forbidden)
    def command(argv, **kw):
        if failure == 'json' and argv[:4] == ['gh','variable','set','ULUCKS_CONFIG_JSON']:
            raise mod.SetupError('simulated variable failure')
        if failure == 'delete' and argv[:3] == ['gh','variable','delete']:
            raise mod.SetupError('simulated variable failure')
        return fake(argv, **kw)
    monkeypatch.setattr(mod, 'command', command)
    monkeypatch.setattr('tatemono_map.cloud.storage.GCSStore', lambda *a, **kw: store)
    monkeypatch.setattr(sys, 'argv', ['setup','--config',str(settings),'--apply','--activate','--prepared-iam','--no-dispatch',
        '--collection-config-env','--collection-file',str(contract),'--resume-bootstrap','--previous-reviewed-commit','b'*40,
        '--reviewed-commit','a'*40,'--expected-job-image','approved-image','--master',str(master),
        '--master-sha256',sha256(master),'--output',str(output)])
    if failure:
        with pytest.raises(mod.SetupError, match='simulated variable failure'): mod.main()
    else:
        mod.main()
    assert store.read_head() == (before_head, before_generation)
    assert {p: p.read_bytes() for p in work.iterdir()} == before_files
    assert {name: (ref, path.read_bytes()) for name, (ref, path) in store.objects.items()} == before_objects
    assert store.downloads == [state['master']['object'], state['public']['object']]
    assert not any(c[0] == 'gcloud' and c[1] == 'secrets' and c[2] not in ('list','describe','versions') for c in fake.calls)
    assert not any(c[:3] == ['gcloud','secrets','versions'] and c[3] != 'list' for c in fake.calls)
    enabled = [c for c in fake.calls if c[:4] == ['gh','variable','set','CLOUD_ENABLED']]
    assert bool(enabled) == (failure is None)
    assert {'name': 'UNRELATED', 'value': 'preserve-me'} in fake.variables
    assert not any(c[1:3] == ['workflow','run'] for c in fake.calls)
