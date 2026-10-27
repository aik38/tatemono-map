"""Mansion Review's dedicated cloud entry, independent of desktop sessions."""
from __future__ import annotations
import argparse
import json
import os
import signal
import tempfile
import time
from pathlib import Path
from tatemono_map.cloud.mansion_crawl import Fetcher,collect
from tatemono_map.cloud.mansion_geography import AREAS,MUNICIPALITIES
from tatemono_map.cloud.realpro_weekly import read_json,save_json,wait_for_shared_lease,weekly_start,upstream_status,verify_web
from tatemono_map.cloud.storage import GCSStore
from tatemono_map.cloud.run import new_run_id


def wait_for_upstream(project,region,*,weekly,timeout=64800):
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials,_=google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    session=AuthorizedSession(credentials);deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        states={}
        for job in ('tatemono-collection-poc','tatemono-realpro-weekly'):
            url=f'https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job}/executions'
            executions=[];token=None
            while True:
                params={'pageSize':100}
                if token:params['pageToken']=token
                response=session.get(url,params=params,timeout=60)
                if response.status_code!=200:raise ValueError('mansion_upstream_status_unavailable:'+job)
                payload=response.json();executions.extend(payload.get('executions',[]));token=payload.get('nextPageToken')
                if not token:break
            states[job]=upstream_status(executions,weekly_start()) if weekly else ('running' if any(not e.get('completionTime') for e in executions) else 'finished')
        if all(s=='finished' for s in states.values()):return states
        print(json.dumps({'stage':'mansion_waiting_for_upstream','states':states}),flush=True);time.sleep(60)
    raise ValueError('mansion_upstream_wait_timeout')


def execute(store,work,*,cycle,source_commit,acquire_only=False,commit=False,verify=False):
    work.mkdir(parents=True,exist_ok=True)
    prefix=f'private-inputs/mansion-review/cycles/{cycle}'
    integrated=read_json(store,prefix+'/integration.json')
    if integrated:
        if verify:integrated['web']=verify_web(integrated['head'])
        return integrated
    latest,_=store.read_head()
    if latest.get('report',{}).get('mansion_cycle')==cycle:
        # Recover a committed CAS whose integration-receipt response was lost.
        result={'status':'committed','run_id':latest['run_id'],'head':latest,
            **{k:latest['report'][k] for k in ('counts_before','counts_after','row_counts','public_counts','successful_scopes','absent_scopes','failed_scopes')}}
        save_json(store,work,prefix+'/integration.json',result)
        if verify:result['web']=verify_web(latest)
        return result
    run=new_run_id()
    receipt=read_json(store,prefix+'/acquisition.json')
    if receipt:
        result_path=work/'acquisition.json';store.download(receipt['result_ref'],result_path)
        acquisition=json.loads(result_path.read_text())
    else:
        fetcher=Fetcher(work/'http',store,cycle)
        results,catalogs=collect(fetcher)
        # Include all immutable receipts, including scopes resumed from a prior
        # task attempt. No source page is refetched to rebuild the manifest.
        originals=[]
        for blob in store.bucket.list_blobs(prefix=prefix+'/http/'):
            if blob.name.endswith('.json'):
                generation=int(blob.generation)
                originals.append(json.loads(blob.download_as_bytes(if_generation_match=generation)))
        acquisition={'cycle':cycle,'source_commit':source_commit,'areas':AREAS,'municipalities':len(MUNICIPALITIES),
            'results':results,'catalogs':catalogs,'originals':originals}
        result_ref=save_json(store,work,f'private-runs/{run}/mansion-acquisition.json',acquisition)
        receipt={'cycle':cycle,'run_id':run,'result_ref':result_ref}
        # Failed scopes are retryable using the successful HTTP/scope receipts.
        if not any(r['status']=='failed' for r in results):save_json(store,work,prefix+'/acquisition.json',receipt)
    if acquire_only:return {'status':'acquired','run_id':run,**receipt}
    from tatemono_map.cloud.mansion_integrate import integrate
    result=integrate(store,work,run,acquisition,source_commit,commit=commit)
    if commit:
        save_json(store,work,prefix+'/integration.json',result)
    if verify and commit:result['web']=verify_web(result['head'])
    save_json(store,work,f'private-runs/{run}/mansion-final-result.json',result)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--weekly',action='store_true');p.add_argument('--cycle')
    p.add_argument('--acquire-only',action='store_true');p.add_argument('--commit',action='store_true');p.add_argument('--verify-web',action='store_true')
    args=p.parse_args()
    cycle=args.cycle or weekly_start().strftime('week-%Y%m%d')
    if not all(c.isalnum() or c in '-_' for c in cycle):raise ValueError('invalid_mansion_cycle')
    store=GCSStore(os.environ['TATEMONO_BUCKET'])
    wait_for_upstream(os.environ['GOOGLE_CLOUD_PROJECT'],os.environ.get('TATEMONO_REGION','asia-northeast1'),weekly=args.weekly)
    wait_for_shared_lease(store)
    # Waiting happens outside the lease. A six-hour processing deadline stays
    # below its seven-hour TTL even when upstream jobs needed a long wait.
    def processing_timeout(signum,frame):raise TimeoutError('mansion_processing_deadline')
    signal.signal(signal.SIGALRM,processing_timeout);signal.alarm(21600)
    with store.collection_lease('mansion-review:'+cycle),tempfile.TemporaryDirectory(prefix='mansion-') as directory:
        result=execute(store,Path(directory),cycle=cycle,source_commit=os.environ['TATEMONO_SOURCE_COMMIT'],
            acquire_only=args.acquire_only,commit=args.commit,verify=args.verify_web)
    signal.alarm(0)
    summary={k:v for k,v in result.items() if k not in ('head','scopes')}
    print('MANSION_RESULT_JSON='+json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
