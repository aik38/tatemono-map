"""Read-only diagnosis of the generation-pinned official master; no collection."""
import json
import os
import sqlite3
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit
from tatemono_map.cloud.storage import GCSStore, validate_head
from tatemono_map.cloud.pipeline import validate_master
from tatemono_map.building_registry.normalization import normalize_building_input, normalize_address_for_matching
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
            groups[norm.normalized_name].append(b)
    candidates = []
    for name, bs in groups.items():
        if len(bs) > 1:
            candidates.append([{'id': b['building_id'], 'name': b['canonical_name'], 'address': b['canonical_address'], 'norm_name': b['norm_name'], 'norm_address':b['norm_address'], 'built': b.get('built_year_month'), 'hidden':b['hidden_from_public'], 'effective':sum(r['building_key']==b['building_id'] for r in effective)} for b in bs])
    fields = 'listing_key building_key name address room_label rent_yen area_sqm layout source_kind ingest_run_id updated_at'.split()
    six = []
    for bs in candidates:
        if any(any(s in (b['name'] or '').lower() for s in ('kasumi','ビーライン足原','ギャラクシー西小倉','グローリア','stage','ギャラン二島','エヴァーグリーン')) for b in bs):
            ids = [b['id'] for b in bs]
            six.append({'buildings':bs, 'listings':[{k:r[k] for k in fields} for r in c.execute('SELECT * FROM listings WHERE building_key IN ('+','.join('?' for _ in ids)+')',ids)], 'sources': [dict(r) for r in c.execute('SELECT source,building_id,raw_name,raw_address FROM building_sources WHERE building_id IN ('+','.join('?' for _ in ids)+')',ids)]})
    result = {'counts': {t:c.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in tables}, 'schemas': {t:tables[t] for t in ('raw_units','building_rental_summaries','building_summaries','cloud_collection_rows') if t in tables}, 'effective':len(effective), 'effective_sources':dict(Counter(r['source_kind'] for r in effective)), 'missing_both':len(missing), 'missing_buildings':len({r['building_key'] for r in missing}), 'missing_by_run': {str(k):v for k,v in Counter((r['source_kind'],r['ingest_run_id'],r['updated_at']) for r in missing).items()}, 'missing_sample':[{k:r[k] for k in fields} for r in missing[:12]], 'candidate_groups':candidates, 'six':six, 'snapshots':[dict(r) for r in c.execute('SELECT * FROM current_ingest_snapshots')], 'ingest_runs':[dict(r) for r in c.execute('SELECT * FROM ingest_runs WHERE id IN ('+','.join('?' for _ in {r['ingest_run_id'] for r in missing})+')',list({r['ingest_run_id'] for r in missing}))]}
    return result


def main():
    work=Path('work/quality-audit');work.mkdir(parents=True,exist_ok=True)
    store=GCSStore(os.environ['GCP_BUCKET']);head,generation=store.read_head();validate_head(head)
    store.download(head['master'],work/'master.sqlite3');validate_master(work/'master.sqlite3')
    report=audit(work/'master.sqlite3')
    report['head']={k:head[k] for k in ('run_id','source_commit','master','public')};report['generation']=generation
    report['public_counts']=head['report']['public_counts']
    # Only normalized property identities and numeric terms enter the safe report.
    # PDF URLs, credentials, PDF contents and the private SQLite never leave GCS/runner.
    print('QUALITY_AUDIT_JSON='+json.dumps(report,ensure_ascii=False,default=str),flush=True)

if __name__=='__main__': main()
