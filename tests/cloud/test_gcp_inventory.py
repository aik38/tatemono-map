import copy

import pytest

from tatemono_map.cloud.gcp_inventory import job_inventory


def job():
    return {"apiVersion": "run.googleapis.com/v1", "kind": "Job",
            "metadata": {"name": "tatemono-collection-poc", "labels": {"managed-by": "test"}, "annotations": {"private": "DO_NOT_RETAIN"}},
            "spec": {"template": {"spec": {"template": {"spec": {
                "containers": [{"image": "asia-northeast1-docker.pkg.dev/tatemono-map/registry/collector@sha256:abc", "env": [{"name": "PRIVATE", "value": "DO_NOT_RETAIN"}], "args": ["DO_NOT_RETAIN"]}],
                "serviceAccountName": "original@tatemono-map.iam.gserviceaccount.com",
            }}}}}}


def test_full_v1_job_preserves_image_and_identity_without_private_settings():
    resource = job()
    before = copy.deepcopy(resource)
    safe = job_inventory(resource)
    task = safe["spec"]["template"]["spec"]["template"]["spec"]
    assert task["containers"] == [{"image": resource["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]["image"]}]
    assert task["serviceAccountName"] == "original@tatemono-map.iam.gserviceaccount.com"
    assert "DO_NOT_RETAIN" not in str(safe)
    assert resource == before


@pytest.mark.parametrize("containers", [[], None, {}, [{"image": ""}], [{"image": None}], [{"env": "DO_NOT_RETAIN"}]])
def test_invalid_container_metadata_fails_with_no_private_error_content(containers):
    resource = job()
    resource["spec"]["template"]["spec"]["template"]["spec"]["containers"] = containers
    with pytest.raises(ValueError, match="^invalid_cloud_run_v1_job_metadata$"):
        job_inventory(resource)


def test_absent_service_account_is_preserved_as_default_not_invented_identity():
    resource = job()
    del resource["spec"]["template"]["spec"]["template"]["spec"]["serviceAccountName"]
    assert job_inventory(resource)["spec"]["template"]["spec"]["template"]["spec"]["serviceAccountName"] == ""
