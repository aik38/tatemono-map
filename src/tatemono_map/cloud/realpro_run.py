"""Independent RealPro job; shared lease and HEAD CAS protect Ulucks releases."""
from __future__ import annotations
import argparse
import json
import os
import tempfile
from contextlib import nullcontext
from pathlib import Path

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.run import new_run_id, secret_json
from tatemono_map.cloud.storage import GCSStore, validate_head, commit_release, RUN_RE
from tatemono_map.cloud.pipeline import validate_master
from tatemono_map.cloud.realpro import collect, COMPANY, COMPANY_ID
from tatemono_map.cloud.realpro_pipeline import update


def execute(store, config, work, source_commit, *, reuse=None, acquire_only=False, dry_run=False):
    run = new_run_id()
    print(json.dumps({'stage':'realpro_started','run_id':run}),flush=True)
    head, generation = store.read_head();validate_head(head)
    old_head = work/'previous-head.json';old_head.write_text(json.dumps(head))
    store.upload(old_head,f'private-runs/{run}/previous-head.json')
    if reuse:
        if not RUN_RE.fullmatch(reuse):raise CollectionError('realpro_invalid_reuse_run')
        manifest_blob = store.bucket.blob(f'private-runs/{reuse}/realpro-acquisition.json')
        manifest_blob.reload();g=int(manifest_blob.generation)
        manifest=json.loads(manifest_blob.download_as_bytes(if_generation_match=g))
        if manifest['config'] != config:raise CollectionError('realpro_reuse_scope_changed')
        pdf=work/'realpro.pdf';store.download(manifest['pdf'],pdf);evidence=manifest['evidence']
    else:
        credentials = secret_json(os.environ['REALPRO_LOGIN_SECRET'])
        pdf,evidence = collect(config,credentials,work/'pdf')
        manifest={'config':config,'pdf':store.upload(pdf,f'private-runs/{run}/pdf/realpro.pdf'),'evidence':evidence}
    manifest_path=work/'realpro-acquisition.json';manifest_path.write_text(json.dumps(manifest,ensure_ascii=False))
    manifest_ref=store.upload(manifest_path,f'private-runs/{run}/realpro-acquisition.json')
    print(json.dumps({'stage':'pdf_acquired','run_id':run,'pdf_count':1,'pdf_pages':evidence['pdf_pages'],
        'expected_rows':evidence['expected_rows'],'fresh':not bool(reuse)}),flush=True)
    if acquire_only:return {'status':'acquired','run_id':run}
    master, baseline = work/'master.sqlite3',work/'baseline.sqlite3'
    store.download(head['master'],master);validate_master(master)
    store.download(head['public'],baseline)
    backup = store.upload_verified(master,f'backups/{run}.sqlite3')
    print(json.dumps({'stage':'backup_verified','run_id':run,'previous_head_generation':generation}),flush=True)
    report=update(master,pdf,evidence,config,work,run,baseline)
    report.update(acquisition_manifest_ref=manifest_ref,backup_ref=backup,newly_acquired_pdf_count=0 if reuse else 1)
    result=work/'report.json';result.write_text(json.dumps(report,ensure_ascii=False))
    store.upload(result,f'private-runs/{run}/realpro-report.json')
    if dry_run:
        return {'status':'dry_run_passed','run_id':run,'report':{k:report[k] for k in ('parsed_rows','parsed_buildings','row_counts','new_buildings','counts_before','counts_after')}}
    committed=commit_release(store,work,run,generation,report,source_commit)
    return {'status':'committed','run_id':run,'master':committed['master'],'public':committed['public'],
        'report':{k:report[k] for k in ('parsed_rows','parsed_buildings','row_counts','new_buildings','counts_before','counts_after')}}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reuse-run');parser.add_argument('--acquire-only',action='store_true');parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    os.umask(0o077)
    config=json.loads(os.environ.get('REALPRO_CONFIG_JSON',json.dumps({'company_id':COMPANY_ID,'company_label':COMPANY,'max_drop_ratio':0.25})))
    try:
        store=GCSStore(os.environ['TATEMONO_BUCKET'])
        if not args.acquire_only:
            required={'storage.objects.get','storage.objects.create','storage.objects.delete','storage.objects.list'}
            if not required <= set(store.bucket.test_iam_permissions(sorted(required))):
                raise CollectionError('realpro_runtime_storage_permissions_insufficient')
        # PDF-only acquisition appends private objects and cannot update HEAD.
        # It therefore needs no production collection lease or delete access.
        lease=nullcontext() if args.acquire_only else store.collection_lease(new_run_id())
        with lease,tempfile.TemporaryDirectory(prefix='realpro-cloud-') as directory:
            result=execute(store,config,Path(directory),os.environ['TATEMONO_SOURCE_COMMIT'],
                reuse=args.reuse_run,acquire_only=args.acquire_only,dry_run=args.dry_run)
        print('REALPRO_SAFE_RESULT='+json.dumps(result,ensure_ascii=False),flush=True)
        return 0
    except CollectionError as exc:
        print(json.dumps({'status':'failed','code':str(exc)}),flush=True);return 1
    except Exception:
        print('{"status":"failed","code":"realpro_cloud_operation_failed"}',flush=True);return 1


if __name__=='__main__':raise SystemExit(main())
