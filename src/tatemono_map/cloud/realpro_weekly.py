"""RealPro acquisition adapter into the unchanged, production PDF batch importer.

The normal entry point requires a finished Ulucks execution for this week's
Monday 04:00 JST. Company receipts are private and survive task retries; failure
never means an empty snapshot. Only integration takes the shared HEAD lease.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.realpro import login, discover, choose, acquire, room_count
from tatemono_map.cloud.run import new_run_id, secret_json
from tatemono_map.cloud.storage import GCSStore, commit_release, validate_head


def monday_start(now=None):
    current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Tokyo'))
    return (current - timedelta(days=current.weekday())).replace(hour=4, minute=0, second=0, microsecond=0)


def upstream_status(executions, since):
    """All live executions block, regardless of the latest execution's outcome."""
    if any(not e.get('completionTime') for e in executions):
        return 'running'
    recent = [e for e in executions if datetime.fromisoformat(e['createTime'].replace('Z', '+00:00')) >= since]
    return 'finished' if recent else 'not_started'


def wait_for_ulucks(project, region, *, timeout=18000):
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    session = AuthorizedSession(credentials)
    url = f'https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/tatemono-collection-poc/executions'
    since = monday_start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        executions = []
        token = None
        while True:
            params = {'pageSize': 100}
            if token: params['pageToken'] = token
            response = session.get(url, params=params, timeout=60)
            if response.status_code != 200:
                raise CollectionError('realpro_ulucks_execution_status_unavailable')
            payload = response.json()
            executions.extend(payload.get('executions', []))
            token = payload.get('nextPageToken')
            if not token: break
        status = upstream_status(executions, since)
        if status == 'finished':
            return {'job': 'tatemono-collection-poc', 'state': status, 'week_start': since.isoformat()}
        print(json.dumps({'stage': 'waiting_for_ulucks', 'state': status}), flush=True)
        time.sleep(60)
    raise CollectionError('realpro_ulucks_wait_timeout')


def read_json(store, name):
    from google.api_core.exceptions import NotFound
    blob = store.bucket.blob(name)
    try: blob.reload()
    except NotFound: return None
    return json.loads(blob.download_as_bytes(if_generation_match=int(blob.generation)))


def save_json(store, work, name, data):
    path = work / 'receipt.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return store.upload_verified(path, name)


def wait_for_shared_lease(store, *, timeout=7200):
    """Check canonical-store contention before collecting; never steal a live lease."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lease = read_json(store, 'state/collection-lock.json')
        if lease is None or float(lease.get('expires_at', float('inf'))) < time.time():
            return
        print(json.dumps({'stage': 'waiting_for_canonical_lease'}), flush=True)
        time.sleep(60)
    raise CollectionError('realpro_canonical_store_busy')


@contextmanager
def acquisition_lease(store, owner):
    """RealPro-only lock: collection must never block the Ulucks shared lease."""
    from google.api_core.exceptions import PreconditionFailed
    blob = store.bucket.blob('state/realpro-acquisition-lock.json')
    payload = json.dumps({'owner': owner, 'expires_at': time.time() + 7 * 3600})
    try:
        blob.upload_from_string(payload, content_type='application/json', if_generation_match=0)
    except PreconditionFailed:
        blob.reload()
        generation = int(blob.generation)
        old = json.loads(blob.download_as_bytes(if_generation_match=generation))
        if old.get('expires_at', float('inf')) >= time.time():
            raise CollectionError('realpro_acquisition_already_running') from None
        blob.upload_from_string(payload, content_type='application/json', if_generation_match=generation)
    generation = int(blob.generation)
    try: yield
    finally:
        try: blob.delete(if_generation_match=generation)
        except Exception: pass


def verify_web(head, *, timeout=5400):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request = Request('https://www.tatemono-map.com/cloud_release.json', headers={'Cache-Control': 'no-cache'})
            with urlopen(request, timeout=45) as response: live = json.load(response)
            if live.get('run_id') == head['run_id'] and live.get('public_sha256') == head['public']['sha256']:
                return {'status': 'verified', 'run_id': live['run_id'], 'counts': live.get('counts')}
        except Exception: pass
        time.sleep(60)
    raise CollectionError('realpro_public_web_sync_pending')


def integrate(store, inputs, work, run, source_commit, manifest_ref, newly_acquired):
    # Reuse production parser / importer / QC / publication scope without forks.
    from tatemono_map.cloud.realpro_batch import backup_current, update_batch, preserve_ulucks_catalog
    with store.collection_lease(run):
        head, generation, backups = backup_current(store, work, run)
        report = update_batch(work/'master.sqlite3', inputs, work, run, work/'baseline.sqlite3',
                              public_preservation_proof=True)
        report.update(original_manifest_ref=manifest_ref, backup_refs=backups,
                      newly_acquired_pdf_count=newly_acquired, collection_mode='automated_realpro_pdf_batch')
        preserve_ulucks_catalog(store, head, run, report)
        save_json(store, work, f'private-runs/{run}/realpro-report.json', report)
        counts = {k: report[k] for k in ('parsed_rows', 'row_counts', 'counts_before', 'counts_after', 'public_counts', 'pdf_count', 'pdf_pages')}
        if not report['attached_rows']:
            return {'status': 'no_new_content', 'head': head, **counts}
        committed = commit_release(store, work, run, generation, report, source_commit)
        return {'status': 'committed', 'head': committed, **counts}


def execute(store, work, *, companies=None, cycle, source_commit, commit=False, verify=False):
    from playwright.sync_api import sync_playwright
    from tatemono_map.cloud.realpro_batch import parse_pdf
    run = new_run_id()
    prefix = f'private-inputs/realpro/cycles/{cycle}'
    previous = read_json(store, prefix + '/integration.json')
    if previous:
        if verify: previous['web'] = verify_web(previous['head'])
        return previous
    credentials = secret_json(os.environ['REALPRO_LOGIN_SECRET'])
    results, inputs, newly_acquired = [], [], 0
    with sync_playwright() as p:
        options = {'headless': True}
        if os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['TATEMONO_CHROMIUM_EXECUTABLE']
        browser = p.chromium.launch(**options)
        try:
            context = browser.new_context(accept_downloads=True, locale='ja-JP', viewport={'width': 1536, 'height': 900})
            page = login(context.new_page(), credentials)
            del credentials
            catalog = discover(page)
            if companies and not companies <= {c['company_id'] for c in catalog}:
                raise CollectionError('realpro_requested_company_not_in_current_catalog')
            save_json(store, work, f'private-runs/{run}/realpro-company-catalog.json', catalog)
            for company in catalog:
                cid = company['company_id']
                result = {**company, 'status': 'unprocessed'}
                results.append(result)
                if companies and cid not in companies:
                    result['status'] = 'not_in_representative_run'; continue
                if company['availability'] != 'available':
                    result['status'] = 'unavailable_empty_link'; continue
                receipt_name = prefix + f'/companies/{cid}/acquisition.json'
                receipt = read_json(store, receipt_name)
                pdf = work / f'realpro-{cid}.pdf'
                try:
                    if receipt:
                        store.download(receipt['pdf'], pdf)
                        result['reused_acquisition'] = True
                    else:
                        regions = choose(page, cid, company['company_label'])
                        if not regions:
                            result['status'] = 'outside_fukuoka_or_no_available_regions'; continue
                        title = page.locator('#company_search .company_room_m').inner_text().strip()
                        towns = page.locator('#company_search input[name="town_code[]"]:checked').evaluate_all(
                            'els=>els.map(e=>e.value)')
                        if not towns or any(not re.fullmatch(r'40\d{6}', t) for t in towns):
                            raise CollectionError('realpro_selected_town_prefecture_mismatch')
                        print(json.dumps({'stage': 'realpro_company_selected', 'company_id': cid,
                                          'regions': len(regions), 'towns': len(towns)}), flush=True)
                        raw_name = prefix + f'/companies/{cid}/download.json'
                        saved_download = read_json(store, raw_name)
                        def preserve_download(path):
                            import hashlib
                            hashed = hashlib.sha256(path.read_bytes()).hexdigest()
                            saved = {'company_title': title, 'regions': regions, 'town_codes': towns,
                                     'acquired_at': datetime.now(timezone.utc).isoformat(), 'sha256': hashed,
                                     'pdf': store.upload_verified(path, f'private-inputs/realpro/originals/{hashed}/{path.name}')}
                            save_json(store, work, raw_name, saved)
                        if saved_download:
                            store.download(saved_download['pdf'], pdf)
                            if saved_download['regions'] != regions or saved_download['town_codes'] != towns:
                                raise CollectionError('realpro_saved_download_scope_changed')
                            count, pages = room_count(pdf)
                            evidence = {'pdf_pages': pages, 'expected_rows': count,
                                        'pdf_sha256': saved_download['sha256'], 'acquired_at': saved_download['acquired_at']}
                        else:
                            pdf, evidence = acquire(page, context, work, cid, on_download=preserve_download)
                            newly_acquired += 1
                        raw_receipt = read_json(store, raw_name)
                        ref = raw_receipt['pdf']
                        receipt = {'company_id': cid, 'company_label': company['company_label'],
                                   'company_title': title, 'regions': regions, 'town_codes': towns,
                                   'pdf': ref, 'evidence': evidence}
                        save_json(store, work, receipt_name, receipt)
                    item = parse_pdf(pdf, work/'parsed')
                    analysis_path = work/'parsed'/(item['metadata']['sha256']+'.json')
                    analysis_ref = store.upload_verified(analysis_path,
                        f'private-runs/{run}/companies/{cid}/parsed.json')
                    if re.sub(r'\s+', '', item['metadata']['company']) != re.sub(r'\s+', '', receipt['company_title']):
                        raise CollectionError('realpro_pdf_company_title_mismatch')
                    if len(item['rows']) != receipt['evidence']['expected_rows'] or item['errors']:
                        raise CollectionError('realpro_pdf_source_accounting_failed')
                    item['metadata']['gcs_ref'] = receipt['pdf']
                    item['metadata']['analysis_ref'] = analysis_ref
                    inputs.append(item)
                    result.update(status='pdf_verified', pdf=receipt['pdf'], evidence=receipt['evidence'],
                                  regions=receipt['regions'], parsed_rows=len(item['rows']))
                except Exception as exc:
                    # Never print provider exception strings: they may contain session URLs.
                    code = str(exc) if isinstance(exc, CollectionError) and re.fullmatch(r'[a-z0-9_]+', str(exc)) else type(exc).__name__
                    result.update(status='failed', failure_code=code)
                    result['failure_location'] = [dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                                                  for f in traceback.extract_tb(exc.__traceback__)[-4:]]
                finally:
                    save_json(store, work, f'private-runs/{run}/companies/{cid}/result.json', result)
                    close = page.locator('#company_room_close')
                    if close.is_visible(): close.click()
                print(json.dumps({'stage': 'realpro_company', 'company_id': cid, 'status': result['status'],
                                  'failure_code': result.get('failure_code'), 'failure_location': result.get('failure_location'),
                                  'parsed_rows': result.get('parsed_rows')}, ensure_ascii=False), flush=True)
        finally: browser.close()
    manifest = {'run_id': run, 'cycle': cycle, 'catalog_count': len(catalog),
                'named_companies': sum(c['availability']=='available' for c in catalog),
                'representative_ids': sorted(companies) if companies else None,
                'companies': results, 'newly_acquired_pdf_count': newly_acquired,
                'failed_companies': sum(r['status']=='failed' for r in results)}
    manifest_ref = save_json(store, work, f'private-runs/{run}/realpro-acquisition-manifest.json', manifest)
    if not inputs: raise CollectionError('realpro_no_verified_pdf_inputs')
    if not commit:
        return {**manifest, 'status': 'acquired_verified'}
    result = integrate(store, inputs, work, run, source_commit, manifest_ref, newly_acquired)
    result.update(acquisition_run_id=run, cycle=cycle, catalog_count=len(catalog),
                  named_companies=manifest['named_companies'], failed_companies=manifest['failed_companies'],
                  newly_acquired_pdf_count=newly_acquired, manifest_ref=manifest_ref)
    # Partial runs remain retryable: saved successful acquisitions are reused.
    if not result['failed_companies']:
        save_json(store, work, prefix+'/integration.json', result)
    if verify: result['web'] = verify_web(result['head'])
    save_json(store, work, f'private-runs/{run}/realpro-final-result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--weekly', action='store_true')
    mode.add_argument('--companies', help='Comma-separated IDs: explicit representative acquisition only')
    parser.add_argument('--cycle')
    parser.add_argument('--commit', action='store_true')
    parser.add_argument('--verify-web', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.weekly:
            wait_for_ulucks(os.environ.get('GOOGLE_CLOUD_PROJECT', 'tatemono-map'),
                            os.environ.get('TATEMONO_REGION', 'asia-northeast1'))
        cycle = args.cycle or ('weekly-'+monday_start().date().isoformat() if args.weekly else None)
        if not cycle or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', cycle):
            raise CollectionError('realpro_cycle_required_or_invalid')
        companies = set(args.companies.split(',')) if args.companies else None
        if companies and (not 2 <= len(companies) <= 3 or any(not c.isdigit() for c in companies)):
            raise CollectionError('realpro_representative_requires_two_or_three_ids')
        store = GCSStore(os.environ['TATEMONO_BUCKET'])
        with acquisition_lease(store, new_run_id()), tempfile.TemporaryDirectory(prefix='realpro-weekly-') as directory:
            if args.weekly: wait_for_shared_lease(store)
            result = execute(store, Path(directory), companies=companies, cycle=cycle,
                             source_commit=os.environ['TATEMONO_SOURCE_COMMIT'], commit=args.commit, verify=args.verify_web)
        safe = {k: v for k, v in result.items() if k not in ('head', 'companies')}
        safe['release_id'] = result.get('head', {}).get('run_id')
        print('REALPRO_WEEKLY_RESULT='+json.dumps(safe, ensure_ascii=False), flush=True)
        return 1 if result.get('failed_companies') else 0
    except CollectionError as exc:
        print(json.dumps({'status': 'failed', 'code': str(exc)}), flush=True)
        return 1
    except Exception as exc:
        frames = [dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                  for f in traceback.extract_tb(exc.__traceback__)[-6:]]
        print(json.dumps({'status': 'failed', 'code': 'realpro_weekly_operation_failed',
                          'type': type(exc).__name__, 'failure_location': frames}), flush=True)
        return 1


if __name__ == '__main__': raise SystemExit(main())
