"""Immutable objects plus one generation-checked master/public commit pointer."""
from __future__ import annotations

import json
import re
from pathlib import Path

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.public_db import sha256, snapshot_sqlite

HEAD = "state/current.json"
RUN_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")


class GCSStore:
    def __init__(self, bucket: str, client=None):
        from google.cloud import storage
        self.bucket = (client or storage.Client()).bucket(bucket)

    def read_head(self) -> tuple[dict, int]:
        blob = self.bucket.blob(HEAD)
        blob.reload()
        generation = int(blob.generation)
        return json.loads(blob.download_as_bytes(if_generation_match=generation)), generation

    def download(self, ref: dict, output: Path) -> None:
        blob = self.bucket.blob(ref["object"], generation=int(ref["generation"]))
        blob.download_to_filename(str(output), if_generation_match=int(ref["generation"]))
        if sha256(output) != ref["sha256"]:
            raise CollectionError("object_checksum_mismatch")

    def upload(self, path: Path, name: str) -> dict:
        blob = self.bucket.blob(name)
        blob.upload_from_filename(str(path), if_generation_match=0)
        return {"object": name, "generation": int(blob.generation), "sha256": sha256(path)}

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
