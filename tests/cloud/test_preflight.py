from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load():
    # Scripts deliberately import their adjacent audit helper, not application
    # modules that could run a collection or invoke a Secret payload API.
    for name in ("audit_master", "preflight_gcp"):
        spec = importlib.util.spec_from_file_location(name, ROOT / "cloud" / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules["preflight_gcp"]


class Blob:
    def __init__(self, name, source, generation=7, fail=False):
        self.name, self.source, self.generation, self.fail = name, source, generation, fail
        self.size, self.updated = source.stat().st_size, None
        self.calls = []

    def download_to_filename(self, target, **kw):
        assert kw == {"if_generation_match": self.generation, "checksum": "auto"}
        self.calls.append(target)
        if self.fail:
            raise RuntimeError("private backend failure must not appear in report")
        shutil.copyfile(self.source, target)


class Bucket:
    name = "existing-private-bucket"
    def __init__(self, blobs):
        self.blobs = blobs
    def list_blobs(self, *, versions):
        assert versions is True
        return self.blobs


class Client:
    def __init__(self, blobs):
        self.blobs = blobs
    def list_buckets(self, *, project):
        assert project == "tatemono-map"
        return [Bucket(self.blobs)]


def test_readonly_audit_downloads_exact_generations_and_rejects_public_and_wal(tmp_path, master):
    mod = load()
    public = tmp_path / "public.sqlite3"
    from tatemono_map.cloud.public_db import export_public, sha256
    export_public(master, public)
    before = sha256(master)
    blobs = [Blob("backups/old.sqlite3", master, 7), Blob("backups/old.sqlite3", master, 8),
             Blob("public/public.sqlite3", public), Blob("unsafe.db", master), Blob("unsafe.db-wal", master)]
    calls = []
    def reader(argv):
        calls.append(argv)
        assert sum(arg.startswith("--format=") for arg in argv) == 1
        if argv[1:4] == ["storage", "buckets", "describe"]:
            assert "--raw" in argv
        assert not any(arg in {"access", "execute", "update", "enable", "add-iam-policy-binding", "create", "set", "upload"} for arg in argv)
        if "versions" in argv:
            assert "tm-ulucks-login" in argv
            return [{"name": "version1", "state": "ENABLED"}]
        return []
    output = tmp_path / "private-output"
    report = mod.inventory(Client(blobs), output, [tmp_path], reader=reader)
    assert report["complete"] and not report["auto_selected"]
    cloud = [row for row in report["candidates"] if row["origin"] == "gcs"]
    assert [r["candidate"] for r in cloud] == [True, True, False, False]
    assert cloud[0]["path"] != cloud[1]["path"]
    assert len({b.calls[0] for b in blobs[:4]}) == 4
    assert all(Path(r["path"]).parent == output / "candidates" for r in cloud)
    assert not any(r["origin"] == "local" and output in Path(r["path"]).parents for r in report["candidates"])
    assert sha256(master) == before
    assert json.loads((output / "report.private.json").read_text())["mode"] == "read_only"
    jobs = next(c for c in calls if c[1:4] == ["run", "jobs", "list"])
    assert "containers.image" in " ".join(jobs) and "containers.env" not in " ".join(jobs)


@pytest.mark.parametrize("failure", ["download", "metadata", "budget"])
def test_failed_or_partial_inventory_is_never_reported_complete(tmp_path, master, monkeypatch, failure):
    mod = load()
    blob = Blob("master.sqlite3", master, fail=failure == "download")
    if failure == "budget":
        monkeypatch.setattr(mod, "MAX_TOTAL_BYTES", 0)
    def reader(argv):
        if failure == "metadata":
            raise RuntimeError("permission denied private data")
        return []
    report = mod.inventory(Client([blob]), tmp_path / "out", [], reader=reader)
    assert not report["complete"] and not report["auto_selected"]
    assert "private data" not in json.dumps(report)


def test_master_with_uncheckpointed_wal_requires_consistent_copy_and_keeps_source_unchanged(tmp_path, master, monkeypatch):
    mod = load()
    with sqlite3.connect(master) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("UPDATE buildings SET canonical_name=canonical_name || '追記'")
        conn.commit()
        assert Path(str(master) + "-wal").stat().st_size > 0
        report = mod.audit(master)
        assert report["wal_present"] and not report["candidate"]
        assert report["decision"] == "standalone_snapshot_required_wal_present"
        from tatemono_map.cloud.public_db import sha256
        before = sha256(master)
        bad = tmp_path / "corrupt.db"
        bad.write_bytes(b"not a database")
        output = tmp_path / "reports" / "audit.json"
        monkeypatch.setattr(sys, "argv", ["audit_master.py", "--candidate", str(master), "--candidate", str(bad), "--output", str(output), "--snapshot-dir", str(tmp_path / "standalone")])
        sys.modules["audit_master"].main()
        snapshots = json.loads(output.read_text())
        assert not snapshots["auto_selected"]
        copied = next(r for r in snapshots["candidates"] if r["candidate"])
        assert not copied["wal_present"]
        with sqlite3.connect(copied["path"]) as snapshot:
            assert snapshot.execute("SELECT COUNT(*) FROM buildings WHERE canonical_name LIKE '%追記'").fetchone()[0] == 2
        assert sha256(master) == before
        assert Path(str(master) + "-wal").stat().st_size > 0
        assert any(r["decision"] == "standalone_snapshot_failed" for r in snapshots["candidates"])
