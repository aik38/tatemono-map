"""Replay only immutable, observed company acquisitions; never infer a zero."""
import json,re,hashlib
from datetime import datetime,timezone
from google.api_core.exceptions import NotFound
from tatemono_map.cloud.collector import Collected,CollectionError,ORIGIN
from tatemono_map.ulucks_geography import AREA_LABELS

def replay_company(store,run,target,config,root):
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}',run):
        raise CollectionError('replay_run_invalid')
    company=target['company_id']
    if not re.fullmatch(r'[0-9]+',company):raise CollectionError('replay_company_invalid')
    name=f'private-runs/{run}/company-{company}-manifest.json'
    blob=store.bucket.blob(name)
    try:blob.reload()
    except NotFound:return None  # A missing saved acquisition requires a live search.
    if blob.size>2*1024*1024:raise CollectionError('replay_manifest_too_large')
    generation=int(blob.generation)
    raw=blob.download_as_bytes(if_generation_match=generation)
    manifest=json.loads(raw)
    original=manifest.get('config',{})
    if (original.get('company_id')!=company or original.get('area_id')!='kitakyushu'
        or original.get('search_url')!=target['search_url']
        or target['search_url']!=ORIGIN+'/company/lists/'+company
        or not isinstance(original.get('company_label'),str) or not original['company_label'].strip()):
        raise CollectionError('replay_scope_identity_changed')
    root.mkdir(parents=True,exist_ok=True)
    evidence_file=root/'evidence.json'
    store.download(manifest['evidence'],evidence_file)
    evidence=json.loads(evidence_file.read_text())
    count=manifest.get('expected_rows')
    if (evidence.get('company_id')!=company or evidence.get('scope_verified') is not True
        or evidence.get('area_labels')!=list(AREA_LABELS)
        or type(count)is not int or not 0<=count<=int(config.get('max_rows',5000))):
        raise CollectionError('replay_scope_evidence_invalid')
    try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(evidence['acquired_at'].replace('Z','+00:00'))).total_seconds()
    except (ValueError,KeyError,TypeError):raise CollectionError('replay_acquisition_time_invalid') from None
    if not 0<=age<=24*3600:return None
    refs=manifest.get('pdfs',[])
    zero=manifest.get('confirmed_zero')
    if (count==0 and (zero is not True or refs or evidence.get('search_counts')!=[0,0])
        or count>0 and (zero is not False or not refs or evidence.get('search_counts')!=[count])):
        raise CollectionError('replay_acquisition_accounting_invalid')
    paths=[]
    prefix=f'private-runs/{run}/companies/{company}/pdf/'
    for index,ref in enumerate(refs):
        if not re.fullmatch(re.escape(prefix)+r'[0-9]{3}\.pdf',str(ref.get('object',''))):
            raise CollectionError('replay_pdf_reference_invalid')
        path=root/f'{index:03d}.pdf';store.download(ref,path);paths.append(path)
    evidence.update(replayed_acquisition_run=run,original_manifest_ref={
        'object':name,'generation':generation,'sha256':hashlib.sha256(raw).hexdigest()})
    one=dict(config,**target,company_label=original['company_label'])
    return one,Collected(paths,count,zero,evidence)
