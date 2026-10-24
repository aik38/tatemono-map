"""One-target Ulucks -> canonical SQLite -> Pages publication, GCP job entry point.

The first run is intentionally gated: bootstrap must use the actual private
canonical SQLite, and a verified Ulucks member-site UI flow is required.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from tatemono_map.cloud.ulucks_flow import fetch_original_pdf, load_flow
from tatemono_map.cli.pdf_batch_run import (
    UlucksParser, apply_name_and_row_filters, dedupe, detect_pdf_kind,
    page_count_fast, qc_check, sha256_file, write_master_import_csv,
)
from tatemono_map.building_registry.ingest_master_import import ingest_master_import_csv, set_current_snapshot
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild

MASTER_POINTER = "master/current.json"
PUBLIC_TABLES = ("buildings", "building_summaries")
OPTIONAL_PUBLIC_TABLES = ("building_key_aliases", "building_rental_summaries", "building_sale_summaries")
GITHUB_REPO = "aik38/tatemono-map"
SITE_INFO = "https://www.tatemono-map.com/build_info.json"


class GateError(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_master(path: Path, *, minimum: int = 1) -> dict:
    if not path.is_file():
        raise GateError("Private canonical SQLite is missing; never bootstrap from public.sqlite3")
    with sqlite3.connect(path) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise GateError("SQLite integrity_check failed")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"buildings", "listings", "ingest_runs", "current_ingest_snapshots", "building_summaries"}.issubset(tables):
            raise GateError("Input is not the private canonical database")
        n = db.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
        if n < minimum:
            raise GateError(f"Canonical count is below minimum: {n} < {minimum}")
        identity = {
            row[0]: (row[1], row[2])
            for row in db.execute("SELECT building_id, canonical_name, canonical_address FROM buildings")
        }
        if len(identity) != n:
            raise GateError("Non-unique canonical building ID")
    return {"buildings": n, "identity": identity}


def make_public(master: Path, output: Path) -> dict:
    """Portable form of publish_public.ps1; only approved tables enter public DB."""
    with sqlite3.connect(master) as src:
        names = {row[0] for row in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(PUBLIC_TABLES).issubset(names):
            raise GateError("Missing public source table")
        selected = PUBLIC_TABLES + tuple(t for t in OPTIONAL_PUBLIC_TABLES if t in names)
        schemas = {}
        for name in selected:
            sql = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
            if not sql or not re.match(r"^CREATE\s+TABLE\s+", sql, re.I):
                raise GateError("Unusable public table DDL")
            schemas[name] = sql
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    try:
        with sqlite3.connect(tmp) as pub:
            pub.execute("PRAGMA foreign_keys=OFF")
            pub.execute("ATTACH DATABASE ? AS source", (str(master),))
            for name in selected:
                pub.execute(schemas[name])
                pub.execute(f'INSERT INTO main."{name}" SELECT * FROM source."{name}"')
            pub.commit()
            pub.execute("DETACH DATABASE source")
            count = pub.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
            listed = pub.execute("SELECT COUNT(*) FROM building_summaries").fetchone()[0]
            if count <= 0 or listed <= 0 or pub.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise GateError("Invalid public DB")
            # Defense in depth: raw, listing/unit records and private evidence never leave GCP.
            actual = {row[0] for row in pub.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if actual != set(selected):
                raise GateError("Unexpected private table in public DB")
        os.replace(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
    return {"public_buildings": count, "public_summaries": listed}


def _storage():
    from google.cloud import storage
    bucket_name = os.environ.get("TM_PRIVATE_BUCKET")
    if not bucket_name or "/" in bucket_name:
        raise GateError("TM_PRIVATE_BUCKET must be an existing private bucket name")
    return storage.Client().bucket(bucket_name)


def _put_immutable(bucket, name: str, content: bytes, content_type: str) -> None:
    blob = bucket.blob(name)
    blob.upload_from_string(content, content_type=content_type, if_generation_match=0)


def bootstrap(bucket, db_path: Path, minimum: int) -> dict:
    state = check_master(db_path, minimum=minimum)
    data = db_path.read_bytes()
    run = uuid.uuid4().hex
    obj = f"master/snapshots/bootstrap-{run}.sqlite3"
    _put_immutable(bucket, obj, data, "application/octet-stream")
    pointer = {"object": obj, "sha256": digest(data), "buildings": state["buildings"]}
    bucket.blob(MASTER_POINTER).upload_from_string(
        json.dumps(pointer), content_type="application/json", if_generation_match=0
    )
    return {"bootstrap": obj, "buildings": state["buildings"], "sha256": pointer["sha256"]}


def _current(bucket, destination: Path):
    blob = bucket.blob(MASTER_POINTER)
    blob.reload()
    generation = int(blob.generation)
    pointer = json.loads(blob.download_as_bytes().decode("utf-8"))
    obj = pointer.get("object", "")
    if not obj.startswith("master/snapshots/") or not obj.endswith(".sqlite3"):
        raise GateError("Untrusted master pointer")
    data = bucket.blob(obj).download_as_bytes()
    if digest(data) != pointer.get("sha256"):
        raise GateError("Master snapshot checksum mismatch")
    destination.write_bytes(data)
    check_master(destination, minimum=int(pointer["buildings"]))
    return pointer, generation


def _lock(bucket, run_id: str):
    lock = bucket.blob("locks/ulucks-publication.lock")
    lock.upload_from_string(run_id, if_generation_match=0)
    return lock


def parse_pdf(pdf: Path, csv_path: Path) -> dict:
    if page_count_fast(pdf) <= 0:
        raise GateError("No readable PDF pages")
    detected = detect_pdf_kind(pdf)
    if detected.kind != "ulucks":
        raise GateError(f"Downloaded PDF not classified as Ulucks: {detected.reason}")
    data = UlucksParser().parse(pdf)
    rows, _, _ = apply_name_and_row_filters(data.df)
    rows, removed = dedupe(rows)
    failures = qc_check(rows, "ulucks") + data.warnings
    if failures:
        raise GateError(f"PDF parse QC failed: {','.join(failures)}")
    if len(rows) == 0:
        raise GateError("No parsed listing rows")
    write_master_import_csv(rows, csv_path)
    return {"pdf_pages": page_count_fast(pdf), "parsed_listings": len(rows), "deduped": removed}


def _github_api(method: str, endpoint: str, *, payload=None):
    token = os.environ.get("TM_GITHUB_PUBLICATION_TOKEN")
    if not token:
        raise GateError("GitHub publication token is not registered in Secret Manager")
    response = requests.request(
        method, "https://api.github.com" + endpoint,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
        json=payload, timeout=90,
    )
    response.raise_for_status()
    return response.json()


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def github_publish(public: Path, run_id: str) -> tuple[str, bool]:
    path = "data/public/public.sqlite3"
    endpoint = f"/repos/{GITHUB_REPO}/contents/{path}"
    previous = _github_api("GET", endpoint + "?ref=main")
    data = public.read_bytes()
    if previous["sha"] == _git_blob_sha(data):
        return "", False
    result = _github_api("PUT", endpoint, payload={
        "message": f"data: publish QC-passed Ulucks snapshot {run_id}",
        "content": base64.b64encode(data).decode("ascii"),
        "sha": previous["sha"], "branch": "main",
    })
    sha = result["commit"]["sha"]
    return sha, True


def verify_pages(commit_sha: str, *, timeout_seconds: int = 480) -> dict:
    """GitHub Pages must serve the commit that contains the accepted public DB."""
    deadline = time.monotonic() + timeout_seconds
    url = SITE_INFO
    while time.monotonic() < deadline:
        try:
            status = _github_api(
                "GET", f"/repos/{GITHUB_REPO}/actions/runs?head_sha={commit_sha}&per_page=10"
            )
            runs = [r for r in status.get("workflow_runs", []) if r.get("name") == "Deploy GitHub Pages"]
            failed = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") != "success"]
            if failed:
                raise GateError(f"Pages workflow failed: {failed[0]['html_url']}")
            successful = [r for r in runs if r.get("conclusion") == "success"]
            if successful:
                live = requests.get(url, headers={"Cache-Control": "no-cache"}, params={"sha": commit_sha},
                                    timeout=20)
                live.raise_for_status()
                info = live.json()
                if info.get("git_sha") == commit_sha and int(info.get("buildings_count_db", 0)) > 0:
                    return {"actions_run": successful[0]["html_url"], "live_git_sha": info["git_sha"],
                            "live_buildings": info["buildings_count_db"]}
        except (requests.RequestException, ValueError):
            pass
        time.sleep(15)
    raise GateError("Pages did not verify expected GitHub commit; master pointer unchanged")


def execute(bucket, *, flow_path: Path, company: str, area: str, minimum: int, publish: bool) -> dict:
    # A single scheduled run must not overlap another writer.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    lock = _lock(bucket, run_id)
    try:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            master = work / "tatemono_map.sqlite3"
            pointer, generation = _current(bucket, master)
            before = check_master(master, minimum=minimum)
            flow = load_flow(flow_path)
            pdf = fetch_original_pdf(flow, company, area, work / "ulucks.pdf")
            raw = pdf.read_bytes()
            original = f"raw/ulucks/{run_id}/original.pdf"
            _put_immutable(bucket, original, raw, "application/pdf")
            ingest_csv = work / "master_import.csv"
            report = parse_pdf(pdf, ingest_csv)
            scope = hashlib.sha256((company + "\0" + area).encode("utf-8")).hexdigest()[:20]
            source = "ulucks:" + scope
            imported = ingest_master_import_csv(str(master), str(ingest_csv), source=source)
            if not imported.ingest_run_id or imported.attached_listings <= 0:
                raise GateError("Ingest produced no attached listings")
            # Avoid a large accidental removal or mismatch before switching current.
            if imported.attached_listings < max(1, report["parsed_listings"] // 2):
                raise GateError("More than half of parsed listings are unmatched; retain previous snapshot")
            with connect(str(master)) as conn:
                set_current_snapshot(conn, source, int(imported.ingest_run_id))
                conn.commit()
            rebuild(str(master))
            after = check_master(master, minimum=before["buildings"])
            if any(after["identity"].get(key) != value for key, value in before["identity"].items()):
                raise GateError("An existing canonical ID/name/address changed")
            public = work / "public.sqlite3"
            public_report = make_public(master, public)
            if public_report["public_buildings"] != after["buildings"]:
                raise GateError("Public building count disagrees with canonical master")

            # Store immutable candidates; current.json remains unchanged until web verification.
            staged_master = f"master/snapshots/{run_id}.sqlite3"
            staged_public = f"staged/{run_id}/public.sqlite3"
            _put_immutable(bucket, staged_master, master.read_bytes(), "application/octet-stream")
            _put_immutable(bucket, staged_public, public.read_bytes(), "application/octet-stream")
            summary = {
                "run_id": run_id, "source": source, "company": company, "area": area,
                "raw_pdf": original, "raw_sha256": digest(raw),
                "pdf_count": 1, **report, "attached_listings": imported.attached_listings,
                "new_buildings": after["buildings"] - before["buildings"], **public_report,
                "staged_master": staged_master, "staged_public": staged_public,
                "published": False,
            }
            if publish:
                # Fail closed when master changed since this run started.
                probe = bucket.blob(MASTER_POINTER)
                probe.reload()
                if int(probe.generation) != generation:
                    raise GateError("Concurrent master update detected before public commit")
                commit_sha, changed = github_publish(public, run_id)
                if changed:
                    summary["github_commit"] = commit_sha
                    summary.update(verify_pages(commit_sha))
                    summary["published"] = True
                else:
                    # An unchanged public DB is a valid no-change weekly outcome.
                    summary["unchanged_public"] = True
                    summary["published"] = True
                next_pointer = {
                    "object": staged_master, "sha256": digest(master.read_bytes()),
                    "buildings": after["buildings"], "previous": pointer["object"],
                    "run_id": run_id, "github_commit": commit_sha,
                }
                probe.upload_from_string(
                    json.dumps(next_pointer), content_type="application/json",
                    if_generation_match=generation,
                )
            _put_immutable(bucket, f"reports/{run_id}.json", json.dumps(summary, ensure_ascii=False).encode(),
                           "application/json")
            return summary
    finally:
        lock.delete(if_generation_match=int(lock.generation))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap-db", type=Path, help="ONE-TIME seed from actual private canonical SQLite")
    ap.add_argument("--flow", type=Path, help="verified member-site UI flow JSON")
    ap.add_argument("--company", default="")
    ap.add_argument("--area", default="")
    ap.add_argument("--minimum-buildings", type=int, default=6975)
    ap.add_argument("--publish", action="store_true", help="explicitly enable public DB commit + Pages verification")
    args = ap.parse_args()
    bucket = _storage()
    if args.bootstrap_db:
        result = bootstrap(bucket, args.bootstrap_db, args.minimum_buildings)
    else:
        if not args.flow or not args.company or not args.area:
            ap.error("--flow, --company and --area required")
        result = execute(bucket, flow_path=args.flow, company=args.company, area=args.area,
                         minimum=args.minimum_buildings, publish=args.publish)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
