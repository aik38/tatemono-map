"""RealPro acquisition adapter into the unchanged, production PDF batch importer.

The normal entry point requires a finished Ulucks execution for this week's
Monday 04:00 JST. Company receipts are private and survive task retries; failure
never means an empty snapshot. Only integration takes the shared HEAD lease.
"""
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
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
    execution = os.environ.get('CLOUD_RUN_EXECUTION')
    task = os.environ.get('CLOUD_RUN_TASK_INDEX')
    attempt = os.environ.get('CLOUD_RUN_TASK_ATTEMPT')
    payload = json.dumps({'owner': owner, 'expires_at': time.time() + 7 * 3600,
        'execution': execution, 'task': task, 'attempt': attempt})

    def ended(old):
        # A managed retry starts only after the preceding task attempt has ended.
        if (execution and old.get('execution') == execution and task is not None
                and old.get('task') == task and str(attempt).isdigit()
                and str(old.get('attempt')).isdigit()):
            return int(attempt) > int(old['attempt'])
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        session = AuthorizedSession(credentials)
        project = os.environ.get('GOOGLE_CLOUD_PROJECT', 'tatemono-map')
        region = os.environ.get('TATEMONO_REGION', 'asia-northeast1')
        base = f'https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/tatemono-realpro-weekly/executions'
        try:
            previous = old.get('execution')
            if previous:
                if not re.fullmatch(r'tatemono-realpro-weekly-[a-z0-9]+', previous): return False
                response = session.get(base+'/'+previous, timeout=60)
                if response.status_code != 200: return False
                return bool(response.json().get('completionTime'))
            # Legacy locks have no execution identity. Never reclaim one early.
            # Once expired, require a unique terminal execution covering its
            # generation timestamp and no other live execution except ourselves.
            if float(old.get('expires_at', float('inf'))) >= time.time(): return False
            if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}', old.get('owner', '')): return False
            executions, token = [], None
            while True:
                params = {'pageSize': 100}
                if token: params['pageToken'] = token
                response = session.get(base, params=params, timeout=60)
                if response.status_code != 200: return False
                data = response.json(); executions.extend(data.get('executions', []))
                token = data.get('nextPageToken')
                if not token: break
            stamp = datetime.strptime(old['owner'][:16], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            if blob.updated is None or abs((blob.updated-stamp).total_seconds()) > 120: return False
            candidates = []
            for entry in executions:
                name = entry['name'].rsplit('/', 1)[-1]
                if name == execution: continue
                if not entry.get('completionTime'): return False
                start = datetime.fromisoformat(entry['createTime'].replace('Z', '+00:00'))
                finish = datetime.fromisoformat(entry['completionTime'].replace('Z', '+00:00'))
                if start <= stamp <= finish: candidates.append(entry)
            return len(candidates) == 1
        except Exception:
            return False
        finally:
            session.close()
    try:
        blob.upload_from_string(payload, content_type='application/json', if_generation_match=0)
    except PreconditionFailed:
        blob.reload()
        generation = int(blob.generation)
        old = json.loads(blob.download_as_bytes(if_generation_match=generation))
        if not ended(old):
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


def company_title(value):
    # Only parentheses and the pre-existing whitespace comparison are normalized.
    return re.sub(r'\s+', '', value.translate(str.maketrans({'（': '(', '）': ')'})))


def run_bounded(command, timeout):
    proc = subprocess.Popen(command, start_new_session=True)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill Chromium, its driver and Python together, including wedged cleanup.
        try: os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        proc.wait(timeout=5)
        raise CollectionError('realpro_company_process_timeout') from None


def company_worker(config):
    from playwright.sync_api import sync_playwright
    from tatemono_map.cloud.realpro_batch import parse_pdf
    store = GCSStore(os.environ['TATEMONO_BUCKET'])
    work = Path(config['work'])
    company = config['company']
    cid = company['company_id']
    prefix, run = config['prefix'], config['run']
    result = {**company, 'status': 'unprocessed'}
    # Existing acquisition receipts are processed without contacting RealPro.
    receipt = read_json(store, prefix + f'/companies/{cid}/acquisition.json')
    with sync_playwright() as p:
        options = {'headless': True}
        if os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['TATEMONO_CHROMIUM_EXECUTABLE']
        browser = p.chromium.launch(**options)
        try:
            context = browser.new_context(accept_downloads=True, locale='ja-JP',
                viewport={'width': 1536, 'height': 900}, storage_state=config['session'])
            page = context.new_page()
            if not receipt:
                # Rebuild selection on a fresh browser connection, also on retry.
                current = discover(page)
                if company not in current:
                    raise CollectionError('realpro_company_identity_changed')
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
                        result['status'] = 'outside_fukuoka_or_no_available_regions'; return result
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
                        result['newly_acquired'] = True
                    raw_receipt = read_json(store, raw_name)
                    ref = raw_receipt['pdf']
                    receipt = {'company_id': cid, 'company_label': company['company_label'],
                               'company_title': title, 'regions': regions, 'town_codes': towns,
                               'pdf': ref, 'evidence': evidence}
                    save_json(store, work, receipt_name, receipt)
                cache_name = prefix + f'/companies/{cid}/parsed.json'
                cached = read_json(store, cache_name)
                if cached is None and config.get('resume_run'):
                    cached = read_json(store, f"private-runs/{config['resume_run']}/companies/{cid}/parsed.json")
                if cached:
                    # parse_pdf independently verifies parser version, actual PDF
                    # SHA-256 and filename before accepting its existing cache.
                    cache = work/'parsed'; cache.mkdir(exist_ok=True)
                    hashed = receipt['pdf']['sha256']
                    if cached.get('metadata', {}).get('sha256') == hashed:
                        (cache/(hashed+'.json')).write_text(json.dumps(cached, ensure_ascii=False))
                item = parse_pdf(pdf, work/'parsed')
                save_json(store, work, cache_name, item)

                analysis_path = work/'parsed'/(item['metadata']['sha256']+'.json')
                analysis_ref = store.upload_verified(analysis_path,
                    f'private-runs/{run}/companies/{cid}/parsed.json')
                if company_title(item['metadata']['company']) != company_title(receipt['company_title']):
                    raise CollectionError('realpro_pdf_company_title_mismatch')
                if len(item['rows']) != receipt['evidence']['expected_rows'] or item['errors']:
                    raise CollectionError('realpro_pdf_source_accounting_failed')
                item['metadata']['gcs_ref'] = receipt['pdf']
                item['metadata']['analysis_ref'] = analysis_ref
                (work/'verified-item.json').write_text(json.dumps(item, ensure_ascii=False))
                result.update(status='pdf_verified', pdf=receipt['pdf'], evidence=receipt['evidence'],
                              regions=receipt['regions'], parsed_rows=len(item['rows']))
            except Exception as exc:
                # Never print provider exception strings: they may contain session URLs.
                code = str(exc) if isinstance(exc, CollectionError) and re.fullmatch(r'[a-z0-9_]+', str(exc)) else type(exc).__name__
                result.update(status='verified_empty' if code == 'realpro_no_published_properties' else 'failed', failure_code=code)
                result['failure_location'] = [dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                                              for f in traceback.extract_tb(exc.__traceback__)[-4:]]

        finally: browser.close()
    return result


def isolated_company(config, *, timeout=900):
    # 2026-10-26 observed maximum selected-to-parsed: 42 s. The 15-minute
    # hard bound also accommodates GCS's existing 600-second transfer retry.
    work = Path(config['work'])
    work.mkdir(parents=True, exist_ok=True)
    config_path = work/'worker.json'
    config_path.write_text(json.dumps(config, ensure_ascii=False))
    output = work/'worker-result.json'
    failures = []
    for attempt in range(2):
        output.unlink(missing_ok=True)
        try:
            code = run_bounded([sys.executable, '-m', 'tatemono_map.cloud.realpro_weekly', '--company-worker', str(config_path)], timeout)
            if code or not output.exists():
                raise CollectionError('realpro_company_worker_failed')
            result = json.loads(output.read_text())
            result['attempts'] = attempt + 1
            if result['status'] != 'failed':
                result['attempt_failures'] = failures
                return result
            failures.append(result['failure_code'])
            # Parsing/identity failures are deterministic and must not redownload.
            if result['failure_code'] not in ('TimeoutError', 'Error', 'realpro_pdf_not_received',
                    'realpro_pdf_http_failed', 'realpro_pdf_response_read_failed',
                    'realpro_company_area_http_failed', 'realpro_selected_company_area_mismatch'):
                return result
        except CollectionError as exc:
            failures.append(str(exc))
    return {**config['company'], 'status': 'failed', 'attempts': 2,
            'failure_code': failures[-1], 'attempt_failures': failures}


def execute(store, work, *, companies=None, cycle, source_commit, commit=False, verify=False, resume_run=None, deadline=None):
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
            session = context.storage_state()
        finally: browser.close()
    budget_exhausted = False
    for company in catalog:
        cid = company['company_id']
        result = {**company, 'status': 'unprocessed'}
        if companies and cid not in companies:
            result['status'] = 'not_in_representative_run'
        elif budget_exhausted or (deadline is not None and time.monotonic() + 1900 > deadline):
            budget_exhausted = True
            result['status'] = 'deferred_time_budget'
        else:
            had_pdf = read_json(store, prefix + f'/companies/{cid}/download.json') is not None
            child_work = work/'companies'/cid
            completed = read_json(store, prefix + f'/companies/{cid}/result.json')
            if completed and completed.get('status') in ('verified_empty', 'outside_fukuoka_or_no_available_regions'):
                result = completed
            else:
                result = isolated_company(dict(work=str(child_work), company=company, prefix=prefix, run=run, session=session, resume_run=resume_run))
            if result['status'] == 'pdf_verified':
                inputs.append(json.loads((child_work/'verified-item.json').read_text()))
            result['newly_acquired'] = not had_pdf and read_json(store, prefix + f'/companies/{cid}/download.json') is not None
            newly_acquired += int(result['newly_acquired'])
        results.append(result)
        if result['status'] in ('verified_empty', 'outside_fukuoka_or_no_available_regions'):
            save_json(store, work, prefix + f'/companies/{cid}/result.json', result)
        save_json(store, work, f'private-runs/{run}/companies/{cid}/result.json', result)
        print(json.dumps({'stage': 'realpro_company', 'company_id': cid, 'status': result['status'],
            'attempts': result.get('attempts'), 'failure_code': result.get('failure_code'),
            'parsed_rows': result.get('parsed_rows')}, ensure_ascii=False), flush=True)
    del session
    manifest = {'run_id': run, 'cycle': cycle, 'catalog_count': len(catalog),
                'named_companies': sum(bool(c['company_label']) for c in catalog),
                'representative_ids': sorted(companies) if companies else None,
                'companies': results, 'newly_acquired_pdf_count': newly_acquired,
                'failed_companies': sum(r['status']=='failed' for r in results),
                'deferred_companies': sum(r['status']=='deferred_time_budget' for r in results),
                'zero_companies': sum(r['status']=='verified_empty' for r in results)}
    manifest_ref = save_json(store, work, f'private-runs/{run}/realpro-acquisition-manifest.json', manifest)
    if not inputs:
        if manifest['deferred_companies']:
            return {**manifest, 'status': 'continuation_required'}
        if manifest['failed_companies']:
            raise CollectionError('realpro_no_verified_pdf_inputs')
        head, _ = store.read_head()
        result = {**manifest, 'status': 'no_new_content', 'head': head}
        if commit: save_json(store, work, prefix+'/integration.json', result)
        if verify: result['web'] = verify_web(head)
        return result
    if not commit:
        return {**manifest, 'status': 'acquired_verified'}
    result = integrate(store, inputs, work, run, source_commit, manifest_ref, newly_acquired)
    result.update(acquisition_run_id=run, cycle=cycle, catalog_count=len(catalog),
                  named_companies=manifest['named_companies'], failed_companies=manifest['failed_companies'],
                  deferred_companies=manifest['deferred_companies'], zero_companies=manifest['zero_companies'],
                  newly_acquired_pdf_count=newly_acquired, manifest_ref=manifest_ref)
    # Partial runs remain retryable: saved successful acquisitions are reused.
    if not result['failed_companies'] and not result['deferred_companies']:
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
    parser.add_argument('--resume-run')
    parser.add_argument('--commit', action='store_true')
    parser.add_argument('--verify-web', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    deadline = time.monotonic() + 20000
    try:
        if args.weekly:
            wait_for_ulucks(os.environ.get('GOOGLE_CLOUD_PROJECT', 'tatemono-map'),
                            os.environ.get('TATEMONO_REGION', 'asia-northeast1'))
        cycle = args.cycle or ('weekly-'+monday_start().date().isoformat() if args.weekly else None)
        if not cycle or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', cycle):
            raise CollectionError('realpro_cycle_required_or_invalid')
        if args.resume_run and not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}', args.resume_run):
            raise CollectionError('realpro_invalid_resume_run')
        companies = set(args.companies.split(',')) if args.companies else None
        if companies and (not 2 <= len(companies) <= 3 or any(not c.isdigit() for c in companies)):
            raise CollectionError('realpro_representative_requires_two_or_three_ids')
        store = GCSStore(os.environ['TATEMONO_BUCKET'])
        with acquisition_lease(store, new_run_id()), tempfile.TemporaryDirectory(prefix='realpro-weekly-') as directory:
            if args.weekly: wait_for_shared_lease(store)
            result = execute(store, Path(directory), companies=companies, cycle=cycle,
                             source_commit=os.environ['TATEMONO_SOURCE_COMMIT'], commit=args.commit, verify=args.verify_web,
                             resume_run=args.resume_run, deadline=deadline)
        safe = {k: v for k, v in result.items() if k not in ('head', 'companies')}
        safe['release_id'] = result.get('head', {}).get('run_id')
        print('REALPRO_WEEKLY_RESULT='+json.dumps(safe, ensure_ascii=False), flush=True)
        return 1 if result.get('failed_companies') or result.get('deferred_companies') else 0
    except CollectionError as exc:
        print(json.dumps({'status': 'failed', 'code': str(exc)}), flush=True)
        return 1
    except Exception as exc:
        frames = [dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                  for f in traceback.extract_tb(exc.__traceback__)[-6:]]
        print(json.dumps({'status': 'failed', 'code': 'realpro_weekly_operation_failed',
                          'type': type(exc).__name__, 'failure_location': frames}), flush=True)
        return 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--company-worker':
        os.umask(0o077)
        config = json.loads(Path(sys.argv[2]).read_text())
        try:
            result = company_worker(config)
        except Exception as exc:
            code = str(exc) if isinstance(exc, CollectionError) and re.fullmatch(r'[a-z0-9_]+', str(exc)) else type(exc).__name__
            result = {**config['company'], 'status': 'failed', 'failure_code': code}
        Path(config['work'], 'worker-result.json').write_text(json.dumps(result, ensure_ascii=False))
    else:
        raise SystemExit(main())

