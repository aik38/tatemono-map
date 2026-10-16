"""Private deployment receipts and allowlisted public failure diagnostics."""
from __future__ import annotations

import json
import re
from pathlib import Path

from tatemono_map.cloud.storage import GCSStore

PERMISSIONS = ('storage.objects.get', 'storage.objects.create', 'storage.objects.list',
               'storage.objects.delete', 'storage.buckets.get')


def safe_error(error):
    """Never return a CLI/SDK message, URL, header, env value or resource name."""
    raw = str(error)
    code = getattr(error, 'code', None)
    if callable(code):
        code = code()
    status = int(code) if str(code).isdigit() else None
    if status is None:
        match = re.search(r'\b(400|401|403|404|408|409|412|429|500|502|503|504)\b', raw)
        status = int(match[1]) if match else None
    return {'status': status, 'permissions': [p for p in PERMISSIONS if p in raw]}


def backup(store, snapshot, name):
    # SDK uses object APIs directly, without gcloud cp's bucket/list discovery.
    # Reuse requires a generation-pinned download and actual SHA-256 match.
    return store.upload_verified(snapshot, name)


def claim(store, name, receipt):
    # Never reconcile an uncertain execution intent into permission to execute.
    store.bucket.blob(name).upload_from_string(json.dumps(receipt, sort_keys=True),
        content_type='application/json', if_generation_match=0)


def exists(store, name):
    from google.api_core.exceptions import NotFound
    blob = store.bucket.blob(name)
    try:
        blob.reload()
    except NotFound:
        return False
    return True


def diagnose(store, directory, name, raw):
    """Raw errors stay private; the public caller emits only safe_error()."""
    path = directory / 'deployment-error.private.log'
    path.write_text(str(raw)); path.chmod(0o600)
    try:
        store.upload_verified(path, name)
    except Exception:
        pass  # Preserve the original failure if diagnostic storage also fails.
