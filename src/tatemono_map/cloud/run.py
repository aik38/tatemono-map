from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tatemono_map.cloud.collector import Collected, CollectionError, collect, validate_config
from tatemono_map.cloud.pipeline import update_master, validate_master
from tatemono_map.cloud.storage import GCSStore, commit_release, validate_head


def secret_json(resource: str) -> dict:
    from google.cloud import secretmanager
    response = secretmanager.SecretManagerServiceClient().access_secret_version(request={"name": resource})
    return json.loads(response.payload.data)


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]


def bootstrap(store, master: Path, expected_sha256: str, work: Path, source_commit: str) -> dict:
    from tatemono_map.cloud.bootstrap import prepare, register
    state = prepare(master, expected_sha256, work, source_commit)
    return register(store, state, work)


def execute(store, config: dict, credentials: dict, work: Path, source_commit: str, collector=collect) -> dict:
    validate_config(config)
    head, generation = store.read_head()
    validate_head(head)
    master = work / "master.sqlite3"
    store.download(head["master"], master)
    validate_master(master)
    run = new_run_id()
    # Pre-update byte-for-byte backup; refusal/failure here prevents collection.
    store.upload(master, f"backups/{run}.sqlite3")
    # The collector writes only allowlisted UI structure, never member HTML.
    # Retain an observation even when live collection later fails.
    observation = work / "ulucks-ui.private.json"
    try:
        collected = collector(config, credentials, work / "pdf")
    except CollectionError as exc:
        if observation.is_file():
            try:
                store.upload(observation, f"private-runs/{run}/ui-observation.json")
            except Exception:
                pass  # Do not replace the original, safely coded collection error.
        exc.run_id = run
        raise
    if observation.is_file():
        try:
            store.upload(observation, f"private-runs/{run}/ui-observation.json")
        except Exception:
            raise CollectionError("ui_observation_private_upload_failed") from None
    if not isinstance(collected, Collected):
        collected = Collected(*collected)
    pdfs, count = collected.pdfs, collected.expected_rows
    for index, pdf in enumerate(pdfs):
        store.upload(pdf, f"private-runs/{run}/pdf/{index:03d}.pdf")
    try:
        report = update_master(master, pdfs, count, config, work, run, confirmed_zero=collected.confirmed_zero)
    except CollectionError as exc:
        diagnostic = work / 'failure.private.json'
        overlap = work / 'overlap-review.private.json'
        diagnostic.write_text(json.dumps({'run_id': run, 'code': str(exc), 'previous_head_unchanged': True, 'overlap_review': json.loads(overlap.read_text()) if overlap.exists() else None}, ensure_ascii=False))
        try:
            store.upload(diagnostic, f'private-runs/{run}/failure.json')
        except Exception:
            pass
        exc.run_id = run
        raise
    report['acquired_at'] = collected.evidence.get('acquired_at')
    evidence = work / "collection-evidence.json"
    evidence.write_text(json.dumps(collected.evidence, ensure_ascii=False))
    store.upload(evidence, f"private-runs/{run}/collection-evidence.json")
    return commit_release(store, work, run, generation, report, source_commit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("collect", "bootstrap"), nargs="?", default="collect")
    parser.add_argument("--bucket", default=os.environ.get("TATEMONO_BUCKET"))
    parser.add_argument("--master", type=Path)
    parser.add_argument("--master-sha256")
    args = parser.parse_args()
    try:
        if not args.bucket:
            raise CollectionError("bucket_not_configured")
        store = GCSStore(args.bucket)
        with tempfile.TemporaryDirectory(prefix="tatemono-cloud-") as directory:
            work = Path(directory)
            source_commit = os.environ["TATEMONO_SOURCE_COMMIT"]
            if args.command == "bootstrap":
                if not args.master or not args.master_sha256:
                    raise CollectionError("bootstrap_master_checksum_required")
                head = bootstrap(store, args.master, args.master_sha256, work, source_commit)
            else:
                config = json.loads(os.environ["ULUCKS_CONFIG_JSON"]) if os.environ.get("ULUCKS_CONFIG_JSON") else secret_json(os.environ["ULUCKS_CONFIG_SECRET"])
                credentials = secret_json(os.environ["ULUCKS_LOGIN_SECRET"])
                head = execute(store, config, credentials, work, source_commit)
            print(json.dumps({"status": "committed", "run_id": head["run_id"], "public_sha256": head["public"]["sha256"]}))
        return 0
    except CollectionError as exc:
        print(json.dumps({"status": "failed", "code": str(exc), "run_id": getattr(exc, 'run_id', None)}), file=sys.stderr)
        return 1
    except Exception:
        # SDK and browser messages can contain signed URLs, cookies or HTML.
        print('{"status":"failed","code":"cloud_operation_failed"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
