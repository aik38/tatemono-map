"""Inspect a preserved acquisition; emit private cases only as RSA-OAEP ciphertext."""
import json,os,re,subprocess,time
from datetime import datetime,timezone

REMOTE = r'''
import json,os,re,csv,io,tempfile,hashlib,base64,subprocess,shutil
from pathlib import Path
from functools import lru_cache
from collections import Counter
from tatemono_map.cloud.storage import GCSStore
from tatemono_map.cloud.pipeline import update_master
from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cli.pdf_batch_run import page_count_fast
from tatemono_map.building_registry import matcher
from tatemono_map.building_registry import ingest_master_import as imp
from tatemono_map.cloud.public_db import readonly
RUN = "20261017T160944Z-10bd49a595a4"
PUBLIC_KEY_PEM = "-----BEGIN PUBLIC KEY-----\nMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA1zKrcMQeS1qA+dezWo9L\nh41n5NoIKIzScdCKXaqpWHCj3/kF1/IwbkfN8LgMFwqOD6aq40u1bP1IJOamkeAx\nMRYbZcyugLcD+c0fCD3gMXG2CNGZfmwNEsofTkhjH5Wdt+ryVJKfNRGr7FbBKZ0t\nFQebn4pFUHSgnwYd7JzuRxl7myS9YN8C1AGkss6dpCB6AxwBpmc0+PG4lsFZPYXZ\n9ExTNL6cM5v7cZ4uAIkiysUFqE/hauApgw/YVGc9nAplYv+HN0Q+amFwKf98sG2T\nLp2P7x/Y98xfjrBRULrgXVpoo2kIm6mlx89RhPUFYdHZBXFwFYojDc/q2GG7rZEA\nVKVH9DCX0ro8J+7m6VMJXzg8cdqZrTZuPd4BwxytBqsE5Qemzby/skFQU4maboFI\nv5enN5Slvu5Uqa0OtGJBVPNJxfJxL06UDoMw7ZGZQ7aoeX/Phpte7wd7Q8AP+KSD\nKGOnAWf/WC6/AiQggRmgR30VrbEC2uALqATgecrc25YrkaqcOBgz+vQ0CSP17S75\nk4DxVHLBhwnXtRWxLb2Hz5Y0Q7cBG5Btzdb4p1IBsr6S1HwTfRRbk8ZvQtDwhBUp\nsTexlVwvfAlPQwz3056w2K7/fpyu1pWIlQHzgd7LVQgkQbk3u/RUsNHKuQfmu4mQ\nYpTE/1dgAWC+iRwmVNL41CECAwEAAQ==\n-----END PUBLIC KEY-----\n"
try:
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes
        key=load_pem_public_key(PUBLIC_KEY_PEM.encode())
        def encrypt(chunk):return key.encrypt(chunk,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    except ImportError:
        if not shutil.which('openssl'):raise RuntimeError('encryption_runtime_unavailable')
        public_file=Path('/tmp/review-transport-public.pem');public_file.write_text(PUBLIC_KEY_PEM)
        def encrypt(chunk):
            return subprocess.run(['openssl','pkeyutl','-encrypt','-pubin','-inkey',str(public_file),
                '-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],
                input=chunk,capture_output=True,check=True).stdout
    store=GCSStore(os.environ['TATEMONO_BUCKET']);before=store.read_head();head,generation=before
    if head['master']['sha256']!='57f86ec174dadf58df95842862cd9a7e9be9bade9328af1a10d27e33c62fe4e6':
        raise RuntimeError('official_master_changed_refusing_replay')
    config=json.loads(os.environ['ULUCKS_CONFIG_JSON'])
    if config.get('company_id')!='8' or config.get('area_id')!='kitakyushu':raise RuntimeError('staged_target_changed')
    def read(name,path):
        b=store.bucket.blob(name);b.reload()
        b.download_to_filename(str(path),if_generation_match=int(b.generation))
        return {'generation':int(b.generation),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    # Cache only pure string normalization; SQL decisions still read current rows.
    matcher.normalize_address_for_matching=lru_cache(maxsize=65536)(matcher.normalize_address_for_matching)
    matcher.normalize_building_input=lru_cache(maxsize=65536)(matcher.normalize_building_input)
    imp.normalize_address_for_matching=lru_cache(maxsize=65536)(imp.normalize_address_for_matching)
    with tempfile.TemporaryDirectory() as d:
        work=Path(d);master=work/'master.sqlite3';baseline=work/'baseline.sqlite3'
        store.download(head['master'],master);store.download(head['public'],baseline)
        evidence_path=work/'evidence.json';read('private-runs/'+RUN+'/collection-evidence.json',evidence_path)
        evidence=json.loads(evidence_path.read_text())
        if evidence.get('area_id')!='kitakyushu' or not evidence.get('scope_verified') or len(evidence.get('search_counts',[]))!=1:
            raise RuntimeError('acquisition_evidence_invalid')
        responses=evidence.get('responses',[])
        if len(responses)!=1 or responses[0].get('content_type')!='application/pdf':
            raise RuntimeError('acquisition_pdf_manifest_requires_review')
        count=evidence['search_counts'][0];pdf=work/'acquired.pdf'
        pdfref=read('private-runs/'+RUN+'/pdf/000.pdf',pdf)
        report={'acquisition_run':RUN,'pdf_sha256':pdfref['sha256'],'pdf_pages':page_count_fast(pdf),
            'expected_rows':count,'acquired_at':evidence.get('acquired_at'),'company_census':evidence.get('company_census')}
        try:
            result=update_master(master,[pdf],count,config,work,RUN+'-analysis',public_baseline=baseline)
            report['result']=result
        except CollectionError as exc:
            report['failure_code']=str(exc)
        groups={};counts={}
        for file in Path('tmp/review').glob('*.csv'):
            rows=list(csv.DictReader(io.StringIO(file.read_text(encoding='utf-8-sig'))))
            kind='new_buildings' if file.name.startswith('new_buildings_') else 'suspects' if file.name.startswith('suspects_') else 'unmatched'
            counts[kind]=counts.get(kind,0)+len(rows)
            if kind=='new_buildings':continue
            for row in rows:
                k=(row.get('raw_name'),row.get('raw_address'),row.get('reason'))
                if k not in groups:groups[k]={'rows':0,**row}
                groups[k]['rows']+=1
        report['review_counts']=counts
        report['reason_counts']=dict(Counter({str(k[2]):sum(g['rows'] for kk,g in groups.items() if kk[2]==k[2]) for k in groups}))
        report['unique_unresolved_groups']=len(groups)
        values=list(groups.values())
        with readonly(master) as conn:
            buildings=conn.execute('SELECT building_id,canonical_name,canonical_address,norm_name,norm_address FROM buildings').fetchall()
            report['candidate_counts']={'buildings':len(buildings),'listings':conn.execute('SELECT COUNT(*) FROM listings').fetchone()[0]}
            for value in values[:40]:
                given=value.get('candidate_ids') or value.get('candidate_building_ids') or ''
                ids=given.split('|') if given else []
                candidates=[]
                if ids:
                    candidates=[{'id':r[0],'name':r[1],'address':r[2]} for r in buildings if r[0] in ids]
                elif 'close_conflicting_candidate' in str(value.get('reason')):
                    from difflib import SequenceMatcher
                    incoming=imp.normalize_address_for_matching(value.get('normalized_address') or '')
                    ranked=[]
                    for r in buildings:
                        ns=SequenceMatcher(None,value.get('normalized_name') or '',r[3] or '').ratio()
                        ads=SequenceMatcher(None,incoming,imp.normalize_address_for_matching(r[4] or '')).ratio()
                        score=ns*0.65+ads*0.35
                        if score>=0.80:ranked.append((score,r))
                    candidates=[{'id':r[0],'name':r[1],'address':r[2],'score':score} for score,r in sorted(ranked,key=lambda x:x[0],reverse=True)[:3]]
                value['candidate_details']=candidates
        report['groups']=values[:40];report['groups_truncated']=len(values)>40
        report['official_head_unchanged']=store.read_head()==before
        payload=json.dumps(report,ensure_ascii=False).encode()
        if len(payload)>100000:raise RuntimeError('private_review_transport_budget_exceeded')
        chunks=[base64.b64encode(encrypt(payload[i:i+400])).decode() for i in range(0,len(payload),400)]
        print('ENCRYPTED_REVIEW='+json.dumps({'algorithm':'RSA-OAEP-SHA256','chunks':chunks}),flush=True)
        print('REVIEW_INSPECTION_SAFE='+json.dumps({'pdf_pages':report['pdf_pages'],'expected_rows':count,'review_counts':counts,
            'reason_counts':report['reason_counts'],'unique_groups':len(groups),'official_head_unchanged':report['official_head_unchanged']}),flush=True)
except Exception as exc:
    print('REVIEW_INSPECTION_ERROR='+json.dumps({'class':type(exc).__name__}),flush=True)
    raise SystemExit(1)
'''

def main():
    base=['gcloud','--project',os.environ['GCP_PROJECT_ID'],'--quiet']
    def gc(args):
        r=subprocess.run(base+args,text=True,capture_output=True,timeout=1100)
        if r.returncode:
            print(json.dumps({'command_failed':args[:3],'error_classes':sorted(set(re.findall(r'\b(?:PERMISSION_DENIED|INVALID_ARGUMENT|NOT_FOUND|UNAUTHENTICATED|DEADLINE_EXCEEDED)\b',r.stderr)))}),flush=True)
            return None
        return r.stdout
    job=os.environ['GCP_JOB'];region=os.environ['GCP_REGION']
    runs=gc(['run','jobs','executions','list','--job',job,'--region',region,'--format=json'])
    if runs is None or any(not x.get('status',{}).get('completionTime') for x in json.loads(runs)):
        raise SystemExit('active_or_unreadable_executions_refusing_private_inspection')
    start=datetime.now(timezone.utc).isoformat()
    assert '~' not in REMOTE
    outcome=gc(['run','jobs','execute',job,'--region',region,'--args=^~^-c~'+REMOTE,'--wait','--format=json'])
    query='resource.type="cloud_run_job" AND resource.labels.job_name="'+job+'" AND timestamp>="'+start+'"'
    found=False
    for attempt in range(4):
        raw=gc(['logging','read',query,'--limit=100','--order=asc','--format=json'])
        if raw:
            for item in json.loads(raw):
                line=item.get('textPayload') or (item.get('jsonPayload') or {}).get('message','')
                if isinstance(line,str) and line.startswith(('ENCRYPTED_REVIEW=','REVIEW_INSPECTION_SAFE=','REVIEW_INSPECTION_ERROR=')):
                    print(line,flush=True);found=True
        if found:break
        if attempt<3:time.sleep(10)
    if outcome is None or not found:raise SystemExit('private_inspection_or_log_capture_failed')

if __name__=='__main__':main()
