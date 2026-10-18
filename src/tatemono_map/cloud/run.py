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


def all_company_proof_ready(head: dict, source_commit: str) -> bool:
    report=head.get('report',{})
    count=report.get('company_count',0)
    proof=report.get('all_company_proof',{})
    approved=(proof.get('source_commit')==source_commit and type(proof.get('company_count')) is int
        and proof['company_count']>0 and isinstance(proof.get('run_id'),str))
    return (head.get('qc')=='passed' and head.get('source_commit')==source_commit
        and report.get('collection_mode')=='all_companies' and type(count) is int
        and count>0 and (report.get('successful_companies')==count or approved))


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
    public_baseline = None
    if config.get('area_id') == 'kitakyushu':
        public_baseline = work / 'publication-baseline.sqlite3'
        store.download(head['public'], public_baseline)
        from tatemono_map.cloud.public_db import validate_public
        if validate_public(public_baseline) != head['report']['public_counts']:
            raise CollectionError('publication_baseline_counts_mismatch')
    run = new_run_id()
    # Pre-update byte-for-byte backup; refusal/failure here prevents collection.
    store.upload(master, f"backups/{run}.sqlite3")
    print('ULUCKS_COLLECTION_SAFE='+json.dumps({'stage':'backup_verified','run_id':run}),flush=True)
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
    pdf_refs=[]
    for index, pdf in enumerate(pdfs):
        pdf_refs.append(store.upload(pdf, f"private-runs/{run}/pdf/{index:03d}.pdf"))
    evidence = work / "collection-evidence.json"
    evidence.write_text(json.dumps(collected.evidence, ensure_ascii=False))
    evidence_ref=store.upload(evidence, f"private-runs/{run}/collection-evidence.json")
    manifest=work/'acquisition-manifest.json'
    manifest.write_text(json.dumps({'company_id':config['company_id'],'area_id':config['area_id'],
        'expected_rows':count,'confirmed_zero':collected.confirmed_zero,'pdfs':pdf_refs,'evidence':evidence_ref}))
    manifest_ref=store.upload(manifest,f'private-runs/{run}/acquisition-manifest.json')
    from tatemono_map.cli.pdf_batch_run import page_count_fast
    print('ULUCKS_COLLECTION_SAFE='+json.dumps({'stage':'pdf_acquired','run_id':run,'pdf_count':len(pdfs),
        'pdf_pages':sum(page_count_fast(pdf) for pdf in pdfs),'expected_rows':count}),flush=True)
    try:
        report = update_master(master, pdfs, count, config, work, run, confirmed_zero=collected.confirmed_zero, public_baseline=public_baseline)
    except CollectionError as exc:
        diagnostic = work / 'failure.private.json'
        overlap = work / 'overlap-review.private.json'
        diagnostic.write_text(json.dumps({'run_id': run, 'code': str(exc), 'previous_head_unchanged': True, 'overlap_review': json.loads(overlap.read_text()) if overlap.exists() else None}, ensure_ascii=False))
        try:
            store.upload(diagnostic, f'private-runs/{run}/failure.json')
            for review in Path('tmp/review').glob('*.csv'):
                if review.stat().st_size <= 10 * 1024 * 1024:
                    store.upload(review,f'private-runs/{run}/review/{review.name}')
        except Exception:
            pass
        exc.run_id = run
        raise
    report['acquired_at'] = collected.evidence.get('acquired_at')
    report['company_id']=config['company_id']
    report['acquisition_manifest_ref']=manifest_ref
    report['area_id']=config['area_id']
    if collected.evidence.get('reused_acquisition_run'):
        report['reused_acquisition_run']=collected.evidence['reused_acquisition_run']
    review=work/'review-rows.private.csv'
    if review.exists():report['review_ref']=store.upload(review,f'private-runs/{run}/review-rows.csv')
    return commit_release(store, work, run, generation, report, source_commit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("collect", "bootstrap"), nargs="?", default="collect")
    parser.add_argument("--bucket", default=os.environ.get("TATEMONO_BUCKET"))
    parser.add_argument("--master", type=Path)
    parser.add_argument("--master-sha256")
    parser.add_argument('--prove-expansion',action='store_true')
    parser.add_argument('--reuse-acquisition')
    parser.add_argument('--reuse-successful-release')
    parser.add_argument('--replay-acquisition-run')
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
                if config.get('area_id')=='kitakyushu' and config.get('collection_mode')!='all_companies' and not args.reuse_acquisition and not args.prove_expansion:
                    previous,_=store.read_head()
                    validate_head(previous)
                    if previous.get('source_commit')!=source_commit or previous.get('report',{}).get('area_id')!='kitakyushu':
                        print('{"status":"skipped","code":"company_full_area_initial_proof_required"}')
                        return 0
                # Every scheduled all-company execution performs a fresh census.
                # A prior partial release or a code revision cannot disable it.
                with store.collection_lease(new_run_id()):
                    credentials = {} if args.reuse_acquisition else secret_json(os.environ["ULUCKS_LOGIN_SECRET"])
                    if config.get('collection_mode') == 'all_companies':
                        from tatemono_map.cloud.batch import execute_all
                        replay=args.replay_acquisition_run
                        # Explicit operator recovery is time bounded. A future
                        # weekly execution always returns to fresh acquisition.
                        deadline=os.environ.get('ULUCKS_RECOVERY_UNTIL')
                        if not replay and deadline:
                            until=datetime.fromisoformat(deadline.replace('Z','+00:00'))
                            if until.tzinfo is None:raise CollectionError('recovery_deadline_timezone_required')
                            remaining=(until-datetime.now(timezone.utc)).total_seconds()
                            if remaining>3*3600:raise CollectionError('recovery_window_exceeds_limit')
                            if remaining>0:replay=os.environ.get('ULUCKS_RECOVERY_ACQUISITION_RUN')
                        head = execute_all(store, config, credentials, work, source_commit,reuse_release=args.reuse_successful_release,replay_acquisition_run=replay)
                    else:
                        if args.reuse_acquisition:
                            from tatemono_map.cloud.acquisition import reuse_verified
                            collector=lambda cfg,creds,path:reuse_verified(store,args.reuse_acquisition,cfg,path)
                            head=execute(store,config,credentials,work,source_commit,collector=collector)
                        else:
                            head = execute(store, config, credentials, work, source_commit)
            print(json.dumps({"status": "committed", "collection_status": head.get("report",{}).get("collection_status","success"), "run_id": head["run_id"], "public_sha256": head["public"]["sha256"]}))
        return 0
    except CollectionError as exc:
        if str(exc)=='collection_lock_held':
            print('{"status":"skipped","code":"collection_lock_held"}')
            return 0
        print(json.dumps({"status": "failed", "code": str(exc), "run_id": getattr(exc, 'run_id', None)}), file=sys.stderr)
        return 1
    except Exception:
        # SDK and browser messages can contain signed URLs, cookies or HTML.
        print('{"status":"failed","code":"cloud_operation_failed"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
