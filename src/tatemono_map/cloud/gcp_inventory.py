"""Allowlisted metadata from a complete Cloud Run v1 Job response.

Do not feed gcloud field projections to this parser: projections through a
repeated field need not preserve the resource's JSON structure. Full responses
are held only in memory; environment, arguments and annotations are discarded.
"""
from __future__ import annotations


def job_inventory(resource):
    try:
        if resource.get("apiVersion") != "run.googleapis.com/v1" or resource.get("kind") != "Job":
            raise ValueError
        metadata = resource["metadata"]
        name = metadata["name"]
        task = resource["spec"]["template"]["spec"]["template"]["spec"]
        containers = task["containers"]
        if not isinstance(name, str) or not name or not isinstance(containers, list) or not containers:
            raise ValueError
        images = []
        for container in containers:
            image = container["image"]
            if not isinstance(image, str) or not image.strip():
                raise ValueError
            images.append({"image": image})
        account = task.get("serviceAccountName", "")
        labels = metadata.get("labels", {})
        if not isinstance(account, str) or not isinstance(labels, dict):
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError):
        # Never include the response, which could contain private settings.
        raise ValueError("invalid_cloud_run_v1_job_metadata") from None
    return {
        "apiVersion": "run.googleapis.com/v1", "kind": "Job",
        "metadata": {"name": name, "labels": labels},
        "spec": {"template": {"spec": {"template": {"spec": {
            "containers": images, "serviceAccountName": account,
        }}}}},
    }
