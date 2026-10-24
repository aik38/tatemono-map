"""Read-only diagnosis of the generation-pinned official master; no collection."""
import json
import os
import sqlite3
import re
import base64,zlib
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit
from tatemono_map.cloud.storage import GCSStore, validate_head
from tatemono_map.cloud.pipeline import validate_master
from tatemono_map.building_registry.normalization import normalize_building_input, normalize_address_for_matching, normalize_ulucks_name
from tatemono_map.normalize.effective_rentals import effective_rentals


def audit(master):
    c = sqlite3.connect(master); c.row_factory = sqlite3.Row
    tables = {r[0]: r[1] for r in c.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")}
    buildings = {r['building_id']: dict(r) for r in c.execute('SELECT * FROM buildings')}
    effective = effective_rentals(c)
    missing = [r for r in effective if r['rent_yen'] is None and r['area_sqm'] is None]
    groups = defaultdict(list)
    for b in buildings.values():
        norm = normalize_building_input(b['canonical_name'] or '', b['canonical_address'] or '')
        if norm.normalized_name:
            groups[''.join(normalize_ulucks_name(b['canonical_name'] or '').casefold().split())].append(b)
    candidates = []
    for name, bs in groups.items():
        if len(bs) > 1:
            candidates.append([{'id': b['building_id'], 'name': b['canonical_name'], 'address': b['canonical_address'], 'norm_name': b['norm_name'], 'norm_address':b['norm_address'], 'built': b.get('built_year_month'), 'hidden':b['hidden_from_public'], 'effective':sum(r['building_key']==b['building_id'] for r in effective)} for b in bs])
    fields = 'listing_key building_key name address room_label rent_yen area_sqm layout source_kind ingest_run_id updated_at'.split()
    six = []
    for bs in candidates:
        if any(any(s in (b['name'] or '').lower() for s in ('kasumi','ビーライン足原','ギャラクシー西小倉','グローリア','stage','ギャラン二島','エヴァーグリーン')) for b in bs):
            ids = [b['id'] for b in bs]
            six.append({'buildings':bs, 'listings':[{**{k:r[k] for k in fields},'effective':any(e['listing_key']==r['listing_key'] for e in effective)} for r in c.execute('SELECT * FROM listings WHERE building_key IN ('+','.join('?' for _ in ids)+')',ids)], 'sources': [dict(r) for r in c.execute('SELECT source,building_id,raw_name,raw_address FROM building_sources WHERE building_id IN ('+','.join('?' for _ in ids)+')',ids)]})
    result = {'counts': {t:c.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in tables}, 'schemas': {t:tables[t] for t in ('raw_units','building_rental_summaries','building_summaries','cloud_collection_rows') if t in tables}, 'effective':len(effective), 'effective_sources':dict(Counter(r['source_kind'] for r in effective)), 'missing_both':len(missing), 'missing_buildings':len({r['building_key'] for r in missing}), 'missing_by_run': {str(k):v for k,v in Counter((r['source_kind'],r['ingest_run_id'],r['updated_at']) for r in missing).items()}, 'missing_sample':[{k:r[k] for k in fields} for r in missing], 'candidate_groups':candidates, 'six':six, 'snapshots':[dict(r) for r in c.execute('SELECT * FROM current_ingest_snapshots')], 'ingest_runs':[dict(r) for r in c.execute('SELECT * FROM ingest_runs WHERE id IN ('+','.join('?' for _ in {r['ingest_run_id'] for r in missing})+')',list({r['ingest_run_id'] for r in missing}))]}
    from tatemono_map.cloud.legacy_rent_evidence import locate,numeric_fields
    found,diagnostics=locate(c,missing)
    result['legacy_original_evidence']={'matched_rows':len(found),'diagnostics':diagnostics,'field_counts':{str(k):v for k,v in Counter(tuple(numeric_fields(raw)) for raw in found.values()).items()},'samples':[numeric_fields(raw) for raw in list(found.values())[:8]]}
    result['raw_source_kinds']=[tuple(r) for r in c.execute('SELECT provider,source_kind,COUNT(*) FROM raw_sources GROUP BY 1,2')]
    result['missing_source_refs']=[{'kind':r['source_kind'],'file':urlsplit(r['source_url'] or '').path.rsplit('/',1)[-1]} for r in missing[:5]]
    result['raw_examples']=[]
    for r in missing[:3]:
        for raw in c.execute('SELECT content FROM raw_sources WHERE source_url=? LIMIT 1',(r['source_url'],)):
            try: content=json.loads(raw[0])
            except ValueError: content={'text_length':len(raw[0]),'key_present':r['listing_key'] in raw[0], 'rent_tokens':re.findall(r'.{0,15}[0-9][0-9,.]*\s*(?:万円|円).{0,15}',raw[0])[:12], 'area_tokens':re.findall(r'.{0,15}[0-9][0-9,.]*\s*(?:m[²2]|㎡|平米).{0,15}',raw[0])[:12], 'field_labels':re.findall(r'([一-龥ぁ-んァ-ヶーA-Za-z_]{1,20})[：:]',raw[0])[:40]}
            if isinstance(content,dict):result['raw_examples'].append({k:v for k,v in content.items() if k not in ('source_url','management_company','management_phone','raw_block')})
    return result


def main():
    work=Path('work/quality-audit');work.mkdir(parents=True,exist_ok=True)
    store=GCSStore(os.environ['GCP_BUCKET']);head,generation=store.read_head();validate_head(head)
    store.download(head['master'],work/'master.sqlite3');validate_master(work/'master.sqlite3')
    store.download(head['public'],work/'public.sqlite3')
    c=sqlite3.connect(work/'master.sqlite3');c.row_factory=sqlite3.Row
    public=sqlite3.connect(work/'public.sqlite3')
    target={r[0] for r in public.execute('SELECT building_key FROM building_summaries WHERE vacancy_count>0 AND rent_yen_min IS NULL AND area_sqm_min IS NULL')}
    missing=[dict(r) for r in c.execute("SELECT * FROM listings WHERE ingest_run_id=31 AND source_kind='mansion_review_chintai' AND rent_yen IS NULL AND area_sqm IS NULL") if r['building_key'] in target]
    from tatemono_map.cloud.legacy_rent_evidence import locate,numeric_fields
    found,diagnostics=locate(c,missing)
    report={'target_rows':len(missing),'original_hash_matched':len(found),'diagnostics':diagnostics,'samples':[numeric_fields(raw) for raw in list(found.values())[:20]],'field_counts':{str(k):v for k,v in Counter(tuple(numeric_fields(raw)) for raw in found.values()).items()},'all_fields':[numeric_fields(raw) for raw in found.values()]}
    report['generation']=generation
    # Only normalized property identities and numeric terms enter the safe report.
    # PDF URLs, credentials, PDF contents and the private SQLite never leave GCS/runner.
    encoded=base64.b64encode(zlib.compress(json.dumps(report,ensure_ascii=False,default=str).encode())).decode()
    for i in range(0,len(encoded),8000):print('QUALITY_AUDIT_CHUNK='+str(i//8000)+':'+encoded[i:i+8000],flush=True)
    print('QUALITY_AUDIT_END='+str((len(encoded)+7999)//8000),flush=True)

if __name__=='__main__': main()
