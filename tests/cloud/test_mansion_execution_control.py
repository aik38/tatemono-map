"""Synthetic MR control tests: no production HTTP, GCS or Cloud Run executions."""
import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from tatemono_map.cloud import mansion_weekly as weekly, mansion_integrate, mansion_crawl, realpro_weekly
from tatemono_map.cloud.collector import CollectionError

CYCLE='week-20261029'


def scopes():
    results=[dict(kind=kind,municipality=name,status='no_source_page',rows=[])
             for kind in ('chintai','mansion') for name in weekly.MUNICIPALITIES]
    for kind in ('chintai','mansion'):
        row=dict(kind=kind,building_name='架空テストマンション',address='福岡県北九州市小倉北区魚町1-1-1',
            building_url='https://www.mansion-review.jp/mansion/123.html',
            source_url='https://www.mansion-review.jp/'+kind+'/123.html',page_url='synthetic',
            room='101',price_yen=55000 if kind=='chintai' else 10000000,fee_yen=3000,area_sqm=30,
            floor='1階',layout='1LDK',built_raw='',structure='',access='',floor_count='',
            total_units='',deposit='',key_money='',direction='南',reason='',raw='synthetic',evidence_id=kind)
        target=next(r for r in results if r['kind']==kind and r['municipality']=='北九州市小倉北区')
        target.update(city_id='1619',status='success',rows=[row])
    return results


@pytest.fixture
def harness(store,monkeypatch,tmp_path):
    # Model a real completed upstream snapshot; a legacy NULL-ingest fixture is
    # intentionally unsuitable for checking provider preservation during imports.
    from tatemono_map.db.repo import connect
    from tatemono_map.cloud.public_db import export_public,validate_public
    from tatemono_map.cloud.storage import commit_release
    prepared=tmp_path/'upstream';prepared.mkdir()
    store.download(store.head['master'],prepared/'master.sqlite3')
    with connect(prepared/'master.sqlite3') as c:
        c.execute("INSERT INTO ingest_runs(id,source,snapshot_key,status) VALUES (1,'realpro','upstream','completed')")
        c.execute("UPDATE listings SET ingest_run_id=1")
        c.execute("INSERT INTO current_ingest_snapshots(source,ingest_run_id) VALUES ('realpro',1)")
    export_public(prepared/'master.sqlite3',prepared/'public.sqlite3')
    commit_release(store,prepared,'20261016T000001Z-000000000001',store.generation,
                   dict(public_counts=validate_public(prepared/'public.sqlite3'),proof=[]),'a'*40)
    h=SimpleNamespace(store=store,rows=scopes(),calls=0,collided=threading.Event())
    lock=threading.Lock()
    @contextmanager
    def lease(owner):
        if not lock.acquire(blocking=False):
            h.collided.set()
            raise CollectionError('collection_lock_held')
        try:yield
        finally:lock.release()
    store.collection_lease=lease
    store.bucket=SimpleNamespace(list_blobs=lambda **kwargs:[])
    def clone(ref,name):
        stored,path=store.objects[ref['object']]
        assert ref==stored
        return store.upload_verified(path,name)
    store.clone_verified=clone
    def read(s,name):
        value=s.objects.get(name)
        return json.loads(value[1].read_text()) if value else None
    h.read=read
    monkeypatch.setattr(weekly,'read_json',read)
    monkeypatch.setattr(realpro_weekly,'read_json',read)
    monkeypatch.setattr(weekly,'Fetcher',lambda *args:None)
    def collect(fetcher):
        h.calls+=1
        return copy.deepcopy(h.rows),{}
    h.collect=collect
    monkeypatch.setattr(weekly,'collect',collect)
    monkeypatch.setattr(weekly,'verify_web',lambda *a,**k:pytest.fail('Cloud Run must not wait for Pages'))
    return h


def run(h,work):
    with weekly.cycle_lease(h.store,CYCLE,poll=.001,timeout=10):
        return weekly.execute(h.store,work,cycle=CYCLE,source_commit='a'*40,commit=True)


def test_commit_completes_while_web_is_pending_and_duplicate_does_nothing(harness,tmp_path):
    h=harness;before=h.store.generation
    first=run(h,tmp_path/'first')
    objects=copy.deepcopy({k:r for k,(r,p) in h.store.objects.items()})
    head=copy.deepcopy(h.store.head)
    second=run(h,tmp_path/'second')
    assert first==second and h.calls==1 and h.store.generation==before+1
    assert h.store.head==head and {k:r for k,(r,p) in h.store.objects.items()}==objects
    assert first['row_counts']['accepted_existing']==2
    assert first['counts_after']['sale_listings']==first['counts_before']['sale_listings']+1
    assert first['counts_after']['listings']==first['counts_before']['listings']+1
    assert first['counts_after']['buildings']==first['counts_before']['buildings']


def test_simultaneous_starts_collect_and_commit_once(harness,tmp_path,monkeypatch):
    h=harness;entered=threading.Event();original=h.collect;before=h.store.generation
    def collect(fetcher):
        entered.set()
        assert h.collided.wait(5)
        return original(fetcher)
    monkeypatch.setattr(weekly,'collect',collect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(run,h,tmp_path/'first')
        assert entered.wait(5)
        second=pool.submit(run,h,tmp_path/'second')
        assert first.result(timeout=15)==second.result(timeout=15)
    assert h.calls==1 and h.store.generation==before+1


def test_failed_scope_is_retryable_without_partial_head_commit(harness,tmp_path):
    h=harness;original=copy.deepcopy(h.rows);h.rows[0]['status']='failed'
    head,generation=h.store.read_head()
    with pytest.raises(CollectionError,match='mansion_cycle_incomplete'):run(h,tmp_path/'failed')
    assert h.store.read_head()==(head,generation)
    assert not h.read(h.store,f'private-inputs/mansion-review/cycles/{CYCLE}/integration.json')
    h.rows=original
    assert run(h,tmp_path/'retry')['status']=='committed'
    assert h.calls==2 and h.store.generation==generation+1


@pytest.mark.parametrize('stage',['quality','cas'])
def test_integration_failure_propagates_and_retry_reuses_acquisition(harness,tmp_path,monkeypatch,stage):
    h=harness;head,generation=h.store.read_head()
    update=mansion_integrate.update
    if stage=='quality':
        monkeypatch.setattr(mansion_integrate,'update',lambda *a,**k:(_ for _ in ()).throw(ValueError('synthetic_quality_failure')))
    else:h.store.fail_commit=True
    with pytest.raises((ValueError,RuntimeError)):run(h,tmp_path/'failed')
    assert h.store.read_head()==(head,generation)
    assert not h.read(h.store,f'private-inputs/mansion-review/cycles/{CYCLE}/integration.json')
    monkeypatch.setattr(mansion_integrate,'update',update);h.store.fail_commit=False
    assert run(h,tmp_path/'retry')['status']=='committed'
    assert h.calls==1 and h.store.generation==generation+1


def test_cas_success_receipt_failure_recovers_without_second_integration(harness,tmp_path,monkeypatch):
    h=harness;save=weekly.save_json;before=h.store.generation
    def lost(s,work,name,data):
        if name.endswith('/integration.json'):raise RuntimeError('synthetic_lost_receipt')
        return save(s,work,name,data)
    monkeypatch.setattr(weekly,'save_json',lost)
    with pytest.raises(RuntimeError,match='synthetic_lost_receipt'):run(h,tmp_path/'first')
    assert h.store.generation==before+1
    monkeypatch.setattr(weekly,'save_json',save)
    assert run(h,tmp_path/'retry')['status']=='committed'
    assert h.calls==1 and h.store.generation==before+1


@pytest.mark.parametrize('damage',['candidate','failed','wrong_cycle','missing_scope','wrong_counts'])
def test_receipt_existence_is_not_completion(harness,tmp_path,monkeypatch,damage):
    h=harness;result=copy.deepcopy(run(h,tmp_path/'first'));head,generation=h.store.read_head()
    if damage=='candidate':result['status']='validated_candidate'
    elif damage=='failed':result['failed_scopes']=1
    elif damage=='wrong_cycle':result['head']['report']['mansion_cycle']='week-20261022'
    elif damage=='missing_scope':result['head']['report']['scope_results'].pop()
    else:result['public_counts']={}
    monkeypatch.setattr(weekly,'read_json',lambda s,n:result if n.endswith('/integration.json') else h.read(s,n))
    with pytest.raises(CollectionError):run(h,tmp_path/'second')
    assert h.store.read_head()==(head,generation) and h.calls==1


def test_live_lock_timeout_and_unexpected_storage_errors_remain_failures(harness,monkeypatch):
    h=harness
    with h.store.collection_lease('other'):
        with pytest.raises(CollectionError,match='mansion_canonical_store_busy'):
            with weekly.cycle_lease(h.store,CYCLE,timeout=.005,poll=.001):pytest.fail('entered live lease')
    @contextmanager
    def broken(owner):
        raise RuntimeError('synthetic_generation_conflict')
        yield
    monkeypatch.setattr(h.store,'collection_lease',broken)
    with pytest.raises(RuntimeError,match='synthetic_generation_conflict'):
        with weekly.cycle_lease(h.store,CYCLE):pytest.fail('ignored conflict')


def test_successful_http_original_is_restored_without_http(harness,tmp_path,monkeypatch):
    h=harness;url='https://www.mansion-review.jp/chintai/prefecture/40.html'
    original=tmp_path/'original.html';original.write_text('<html>synthetic saved source</html>')
    ref=h.store.upload_verified(original,'private-inputs/mansion-review/originals/test.html')
    key=hashlib.sha256(url.encode()).hexdigest()
    receipt=dict(url=url,sha256=ref['sha256'],ref=ref,http_status=200)
    realpro_weekly.save_json(h.store,tmp_path,f'private-inputs/mansion-review/cycles/{CYCLE}/http/{key}.json',receipt)
    fetcher=mansion_crawl.Fetcher(tmp_path/'http-restored',h.store,CYCLE)
    monkeypatch.setattr(fetcher.session,'get',lambda *a,**k:pytest.fail('refetched successful HTTP'))
    assert fetcher.get(url)==original.read_text()


def test_regional_receipts_resume_only_the_failed_region(harness,tmp_path,monkeypatch):
    h=harness;calls=[]
    monkeypatch.setattr(mansion_crawl,'catalog',lambda html,kind:{n:dict(city_id=str(i),url='synthetic') for i,n in enumerate(weekly.MUNICIPALITIES)})
    def scope(fetcher,kind,name,entry):
        calls.append((kind,name))
        if len(calls)==1:raise ValueError('synthetic_interrupted_region')
        return dict(kind=kind,municipality=name,status='success',rows=[],parser_version=mansion_crawl.VERSION)
    monkeypatch.setattr(mansion_crawl,'collect_scope',scope)
    def fetcher(name):
        path=tmp_path/name;path.mkdir()
        return SimpleNamespace(work=path,store=h.store,cycle=CYCLE,get=lambda url:'synthetic catalog')
    first,_=mansion_crawl.collect(fetcher('first-regions'))
    saved={k:copy.deepcopy(r) for k,(r,p) in h.store.objects.items() if '/scopes/' in k}
    assert len(saved)==69 and sum(r['status']=='failed' for r in first)==1
    second,_=mansion_crawl.collect(fetcher('resumed-regions'))
    assert len(calls)==71 and len(second)==70 and all(r['status']=='success' for r in second)
    assert all(h.store.objects[k][0]==r for k,r in saved.items())


def test_pages_production_verification_and_default_operator_args_are_preserved():
    root=Path(__file__).resolve().parents[2]
    assert 'python -m tatemono_map.cloud.verify_public --production' in (root/'.github/workflows/deploy_pages.yml').read_text()
    operator=(root/'cloud/mansion_operator.py').read_text()
    assert '--args=-m,tatemono_map.cloud.mansion_weekly,--weekly,--commit\'' in operator
    assert '--weekly,--commit,--verify-web' not in operator
