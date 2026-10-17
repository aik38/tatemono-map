"""Immutable objects plus one generation-checked master/public commit pointer."""
from __future__ import annotations

import json
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.public_db import sha256, snapshot_sqlite

HEAD = "state/current.json"
RUN_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
TRANSFER_TIMEOUT = (20, 180)


def transfer_retry():
    from google.cloud.storage.retry import DEFAULT_RETRY_IF_GENERATION_SPECIFIED
    from google.cloud.storage.retry import ConditionalRetryPolicy
    policy = DEFAULT_RETRY_IF_GENERATION_SPECIFIED
    return ConditionalRetryPolicy(policy.retry_policy.with_timeout(600), policy.conditional_predicate, policy.required_kwargs)


class GCSStore:
    def __init__(self, bucket: str, client=None):
        from google.cloud import storage
        self.bucket = (client or storage.Client()).bucket(bucket)

    def read_head(self) -> tuple[dict, int]:
        blob = self.bucket.blob(HEAD)
        blob.reload()
        generation = int(blob.generation)
        return json.loads(blob.download_as_bytes(if_generation_match=generation)), generation

    @contextmanager
    def collection_lease(self, owner):
        """A seven-hour lease exceeds the Job's six-hour maximum lifetime."""
        from google.api_core.exceptions import PreconditionFailed
        blob=self.bucket.blob('state/collection-lock.json')
        value=json.dumps({'owner':owner,'expires_at':time.time()+7*3600})
        try:
            blob.upload_from_string(value,content_type='application/json',if_generation_match=0)
        except PreconditionFailed:
            blob.reload();generation=int(blob.generation)
            old=json.loads(blob.download_as_bytes(if_generation_match=generation))
            if float(old.get('expires_at',float('inf')))>=time.time():
                raise CollectionError('collection_lock_held') from None
            blob.upload_from_string(value,content_type='application/json',if_generation_match=generation)
        generation=int(blob.generation)
        try:
            yield
        finally:
            try:blob.delete(if_generation_match=generation)
            except Exception:pass  # Never mask a committed release or delete another owner's lease.

    def download(self, ref: dict, output: Path) -> None:
        blob = self.bucket.blob(ref["object"], generation=int(ref["generation"]))
        blob.download_to_filename(str(output), if_generation_match=int(ref["generation"]), timeout=TRANSFER_TIMEOUT)
        if sha256(output) != ref["sha256"]:
            raise CollectionError("object_checksum_mismatch")

    def upload(self, path: Path, name: str) -> dict:
        blob = self.bucket.blob(name, chunk_size=UPLOAD_CHUNK_BYTES)
        blob.upload_from_filename(str(path), if_generation_match=0, timeout=TRANSFER_TIMEOUT, retry=transfer_retry(), checksum='crc32c')
        return {"object": name, "generation": int(blob.generation), "sha256": sha256(path)}

    def existing_upload(self, path: Path, name: str) -> dict | None:
        """A remote checksum claim alone never authorizes reusing an object."""
        from google.api_core.exceptions import NotFound
        blob = self.bucket.blob(name)
        try:
            blob.reload(timeout=TRANSFER_TIMEOUT)
        except NotFound:
            return None
        if int(blob.size) != path.stat().st_size:
            raise CollectionError('bootstrap_existing_object_differs')
        ref = {'object': name, 'generation': int(blob.generation), 'sha256': sha256(path)}
        with tempfile.TemporaryDirectory(prefix='tatemono-upload-check-') as directory:
            # Pin the observed generation and hash the actual stored bytes.
            self.download(ref, Path(directory) / 'object')
        return ref

    def upload_verified(self, path: Path, name: str) -> dict:
        """Bootstrap retry only: reconcile a create whose response was lost."""
        existing = self.existing_upload(path, name)
        if existing:
            return existing
        try:
            return self.upload(path, name)
        except Exception:
            # Never overwrite an existing generation or infer that a timeout
            # means the server rejected the bytes. Re-raise if still absent.
            existing = self.existing_upload(path, name)
            if existing:
                return existing
            raise

    def commit(self, head: dict, generation: int) -> None:
        self.bucket.blob(HEAD).upload_from_string(json.dumps(head, sort_keys=True), content_type="application/json", if_generation_match=generation)


def validate_head(head: dict) -> None:
    if head.get("schema") != 1 or head.get("qc") != "passed" or not RUN_RE.fullmatch(head.get("run_id", "")):
        raise CollectionError("unvalidated_release_head")
    run = head["run_id"]
    for key, expected in (("master", f"masters/{run}.sqlite3"), ("public", f"public/releases/{run}/public.sqlite3")):
        ref = head.get(key, {})
        if ref.get("object") != expected or not re.fullmatch(r"[0-9a-f]{64}", ref.get("sha256", "")) or int(ref.get("generation", 0)) <= 0:
            raise CollectionError("invalid_release_object_reference")


def commit_release(store, work: Path, run_id: str, generation: int, report: dict, source_commit: str) -> dict:
    if not RUN_RE.fullmatch(run_id) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise CollectionError("invalid_release_identity")
    # Upload a SQLite backup, not a bare file copy that could omit committed
    # WAL pages when the imported Windows master retains WAL journal mode.
    standalone = work / "master-upload.sqlite3"
    snapshot_sqlite(work / "master.sqlite3", standalone)
    master = store.upload(standalone, f"masters/{run_id}.sqlite3")
    public = store.upload(work / "public.sqlite3", f"public/releases/{run_id}/public.sqlite3")
    head = {"schema": 1, "qc": "passed", "run_id": run_id, "source_commit": source_commit, "master": master, "public": public, "report": report}
    validate_head(head)
    # This is the sole mutable operation. A concurrent winner leaves this run's
    # objects unreferenced; never retry with a freshly read generation.
    store.commit(head, generation)
    return head
