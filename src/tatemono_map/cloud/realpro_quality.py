"""Evidence-checked repair of held RealPro rows, without re-registering PDFs.

Uses PyMuPDF only for independent source verification (pip install pymupdf).
The default creates a disposable candidate; --commit requires the exact saved
HEAD generation and a completed candidate report from the same source commit.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import unicodedata
import zipfile
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import pandas as pd
from tatemono_map.building_registry.ingest_master_import import (
    _has_realpro_lot_address, _listing_key, ingest_master_import_csv,
)
from tatemono_map.building_registry.normalization import normalize_building_input, normalize_ulucks_name
from tatemono_map.cli.pdf_batch_run import write_master_import_csv
from tatemono_map.cloud.partial import literal_room
from tatemono_map.cloud.pipeline import preservation_state, validate_master
from tatemono_map.cloud.public_db import readonly, export_public, rendered_ids, sha256
from tatemono_map.cloud.realpro_batch import (
    backup_current, apply_publication_scope, validate_adopted_rows,
    preserve_ulucks_catalog, fukuoka_address,
)
from tatemono_map.cloud.run import new_run_id
from tatemono_map.cloud.storage import GCSStore, commit_release
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.normalize.effective_rentals import effective_rentals, canonical_key

REASON = 'unmatched_canonical_building:address_not_granular'
REPAIR = 'realpro-lot-evidence-20261024-v1'


def nf(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()


def source_index(archive, expected):
    """Read identity and money independently from PDF text/link coordinates.

    Nonstandard layouts do not produce proof. They remain private instead of
    falling back to the parser whose result is being audited.
    """
    import pymupdf as fitz
    index = {}; unverified = []; all_ids = set(); pages = 0
    with zipfile.ZipFile(archive) as z:
        files = [n for n in z.namelist() if n.lower().endswith('.pdf')]
        hashes = {hashlib.sha256(z.read(n)).hexdigest() for n in files}
        if hashes != set(expected) or len(files) != len(expected):
            raise ValueError('original_inventory_differs_from_official_inputs')
        for filename in sorted(files):
            content = z.read(filename); hashed = hashlib.sha256(content).hexdigest()
            with fitz.open(stream=content, filetype='pdf') as doc:
                pages += len(doc)
                for page_no, page in enumerate(doc, 1):
                    blocks = page.get_text('blocks')
                    headers = sorted([b for b in blocks if '号室名\n' in b[4] and '賃料\n' in b[4]], key=lambda b:b[1])
                    links = {}
                    for link in page.get_links():
                        m = re.search(r'room_detail.php\?id=(\d+)', link.get('uri', ''))
                        if m:
                            if (hashed,m[1]) not in all_ids:all_ids.add((hashed,m[1]))
                            if link['from'].x0 > 40:links[m[1]] = link['from']
                    words = page.get_text('words')
                    for room_id, rect in links.items():
                        key = (hashed, room_id)
                        hs = [b for b in headers if b[3] < rect.y0+5]
                        if not hs:unverified.append([hashed,page_no,room_id,'missing_header']);continue
                        h = hs[-1]; pre = h[4].split('号室名\n',1)[0].splitlines()
                        rb = [b for b in blocks if b[0]<110 and b[1]<rect.y1 and b[3]>rect.y0 and b[1]>h[3]]
                        if len(pre)<2 or len(rb)!=1:
                            unverified.append([hashed,page_no,room_id,'nonstandard_layout']);continue
                        rb=rb[0]; band=[w for w in words if rb[1]-9<=w[1]<=rb[3]+3]
                        def col(lo,hi):
                            return nf(' '.join(w[4] for w in sorted(band,key=lambda w:(round(w[1]/5),w[0])) if lo<=w[0]<hi))
                        if key in index:raise ValueError('duplicate_source_room_proof')
                        index[key] = dict(page=page_no, name=nf(pre[0]),address=nf(pre[1].split(' ／ ')[0]),
                            room=nf(rb[4].splitlines()[0]),layout_area=col(174,230),rent=col(230,284),fee=col(284,335))
    return index, dict(pdf_count=len(files),pdf_pages=pages,source_room_ids=len(all_ids),independently_indexed=len(index),unverified=unverified)


def proof_reason(raw, proof):
    if not proof:return 'source_layout_unverified'
    if any(re.search(r'[?？�]', str(raw.get(k,''))+proof[k2]) for k,k2 in [('building_name','name'),('address','address')]):
        return 'ambiguous_source_identity'
    source_name=re.sub(r'\s+'+re.escape(str(raw['room']))+r'号室$', '',proof['name']).strip()
    source=normalize_building_input(source_name,proof['address'])
    parsed=normalize_building_input(raw['building_name'],raw['address'])
    if (source.normalized_name,source.normalized_address)!=(parsed.normalized_name,parsed.normalized_address):
        return 'source_identity_differs_from_parser'
    if normalize_ulucks_name(source_name)!=normalize_ulucks_name(raw['building_name']):
        return 'source_building_suffix_differs_from_parser'
    if normalize_ulucks_name(raw['building_name'])!=parsed.normalized_name:
        return 'building_number_suffix_needs_review'
    if proof['page']!=raw['page'] or literal_room(proof['room'])!=literal_room(raw['room']):return 'source_room_differs_from_parser'
    if not _has_realpro_lot_address(parsed.normalized_address) or not fukuoka_address(raw['address']):return 'source_address_incomplete_or_annotated'
    for column,field in [('rent','rent_man'),('fee','fee_man')]:
        m=re.match(r'([\d,]+)円(?:\s|$)',proof[column])
        if m:
            if raw.get(field) is None or int(m[1].replace(',',''))!=int(Decimal(str(raw[field]))*10000):return 'source_money_differs_from_parser'
        elif raw.get(field) is not None or not re.match(r'^(?:なし|--?|―)(?:\s|$)',proof[column]):
            return 'source_money_unverified'
    area=re.search(r'([0-9]+(?:\.[0-9]+)?)m2',proof['layout_area'])
    layout=re.match(r'(\d+[A-Z]*LDK|\d+DK|\d+K|1R)\b',proof['layout_area'])
    if not area or abs(float(area[1])-raw['area_sqm'])>1e-6:return 'source_area_differs_from_parser'
    if not layout or layout[1]!=(raw.get('layout') or ''):return 'source_layout_differs_from_parser'
    return ''


def current_rows(c):
    return [dict(r) for r in c.execute("""SELECT q.* FROM cloud_collection_rows q
        JOIN current_ingest_snapshots s ON s.source=q.scope_key AND s.ingest_run_id=q.ingest_run_id
        WHERE q.scope_key LIKE 'realpro:batch:%'""")]


def counts(rows, private):
    result=Counter(r['classification'] for r in rows);result['anomaly']+=private
    return dict(result)


def repair_candidate(master, baseline, archive, work, run):
    validate_master(master)
    with connect(master) as c:
        rows=current_rows(c)
        expected={r[0] for r in c.execute('SELECT sha256 FROM realpro_pdf_inputs')}
        private_rows=[(r[0],item) for r in c.execute("SELECT company,result_json FROM realpro_pdf_inputs WHERE status='private_no_valid_rows'") for item in json.loads(r[1]).get('row_results',[])]
        private=len(private_rows)
        before=counts(rows,private)
        originals={r['building_id']:dict(r) for r in c.execute('SELECT * FROM buildings')}
        preserved=preservation_state(c)
        snapshots=[tuple(r) for r in c.execute('SELECT * FROM current_ingest_snapshots ORDER BY source')]
        ingest={r['id']:dict(r) for r in c.execute('SELECT * FROM ingest_runs')}
        inputs=[tuple(r) for r in c.execute('SELECT * FROM realpro_pdf_inputs ORDER BY sha256')]
        batches=[tuple(r) for r in c.execute('SELECT * FROM realpro_company_batches ORDER BY scope_key,semantic_hash')]
        ulucks={r['listing_key']:r for r in effective_rentals(c) if r['source_kind']=='ulucks'}
        c.execute('''CREATE TABLE IF NOT EXISTS realpro_quality_repairs (
            repair_id TEXT NOT NULL, ingest_run_id INTEGER NOT NULL, evidence_id TEXT NOT NULL,
            previous_classification TEXT NOT NULL, previous_reason TEXT NOT NULL,
            outcome TEXT NOT NULL, detail TEXT NOT NULL, proof_json TEXT NOT NULL,
            PRIMARY KEY(repair_id,ingest_run_id,evidence_id))''')
    index,inventory=source_index(archive,expected)
    if inventory['source_room_ids']!=sum(before.values()):raise ValueError('source_room_accounting_differs')
    identity_groups=defaultdict(list)
    for row in rows:
        raw=json.loads(row['raw_json']);n=normalize_building_input(raw['building_name'],raw['address'])
        identity_groups[n.normalized_name,n.normalized_address,literal_room(raw['room'])].append(row)
    groups=defaultdict(list); decisions=[]; proof_by_evidence={}
    canonical_names=defaultdict(set)
    for original in originals.values():
        canonical_names[normalize_building_input('',original['canonical_address']).normalized_address].add(normalize_ulucks_name(original['canonical_name']))
    for row in rows:
        if row['classification']!='held' or row['reason']!=REASON:continue
        raw=json.loads(row['raw_json']);p=index.get((raw['_pdf_sha256'],str(raw.get('source_room_id',''))))
        detail=proof_reason(raw,p)
        n=normalize_building_input(raw['building_name'],raw['address'])
        names=canonical_names.get(n.normalized_address,set())
        if not detail and names and normalize_ulucks_name(raw['building_name']) not in names:
            detail='existing_address_different_building_name'
        if not detail and len(identity_groups[n.normalized_name,n.normalized_address,literal_room(raw['room'])])>1:
            detail='multiple_source_rows_for_same_unit'
        if not detail:
            groups[row['ingest_run_id']].append((row,raw))
            proof_by_evidence[row['evidence_id']]=p
        else:decisions.append((row,'held',detail,p or {}))
    print(json.dumps({'stage':'source_proof','inventory':{k:v for k,v in inventory.items() if k!='unverified'},
        'eligible':sum(map(len,groups.values())),'held':dict(Counter(x[2] for x in decisions))},ensure_ascii=False),flush=True)
    accepted=[]; initial_ids=set(originals)
    for ingest_id,items in sorted(groups.items()):
        old_run=ingest[ingest_id]; path=work/f'repair-{ingest_id}.csv'
        write_master_import_csv(pd.DataFrame([raw for row,raw in items]),path)
        # Same original run and evidence keys: existing accepted offers are not
        # re-imported, no snapshot is switched, and PDF inputs remain immutable.
        result=ingest_master_import_csv(str(master),str(path),source='realpro',
            snapshot_source=old_run['source'],snapshot_key=old_run['snapshot_key'],strict_name_match=True,exact_name_match=True)
        if result.ingest_run_id!=ingest_id:raise ValueError('repair_created_new_input_run')
        with connect(master) as c:
            with path.open(encoding='utf-8-sig',newline='') as f:
                keyed={r['evidence_id']:hashlib.sha256(f'{ingest_id}:{_listing_key(r)}'.encode()).hexdigest() for r in csv.DictReader(f)}
            queued={r[0]:r[1] for r in c.execute('SELECT evidence_id,reason FROM unmatched_queue WHERE ingest_run_id=? ORDER BY id',(ingest_id,))}
            for row,raw in items:
                e=row['evidence_id'];listing=c.execute('SELECT * FROM listings WHERE listing_key=?',(keyed[e],)).fetchone()
                if listing is None:
                    decisions.append((row,'held',queued.get(e,'unconfirmed'),proof_by_evidence[e]));continue
                # A remediation never relies on fuzzy equivalence. Exact full
                # canonical name/address must identify the resulting building.
                b=c.execute('SELECT canonical_name,canonical_address FROM buildings WHERE building_id=?',(listing['building_key'],)).fetchone()
                n=normalize_building_input(raw['building_name'],raw['address']);bn=normalize_building_input(*b)
                if (normalize_ulucks_name(raw['building_name']),n.normalized_address)!=(normalize_ulucks_name(b[0]),bn.normalized_address):raise ValueError('repair_nonexact_canonical_identity')
                classification='accepted_existing' if listing['building_key'] in initial_ids else 'accepted_new'
                c.execute('''UPDATE cloud_collection_rows SET classification=?,reason='',building_id=?,listing_key=?
                    WHERE scope_key=? AND ingest_run_id=? AND evidence_id=? AND classification='held' AND reason=?''',
                    (classification,listing['building_key'],keyed[e],row['scope_key'],ingest_id,e,REASON))
                c.execute("""UPDATE unmatched_queue SET status='resolved',resolved_building_id=?,resolved_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP WHERE ingest_run_id=? AND evidence_id=? AND status='open'""",(listing['building_key'],ingest_id,e))
                accepted.append(dict(evidence_id=e,building_id=listing['building_key'],listing_key=keyed[e],company=row['company_id'],
                    name=raw['building_name'],address=raw['address'],room=raw['room'],pdf_sha256=raw['_pdf_sha256'],page=raw['page']))
                decisions.append((row,classification,'verified_complete_lot_address',proof_by_evidence[e]))
            c.execute('UPDATE ingest_runs SET '+','.join('"'+k+'"=?' for k in old_run if k!='id')+' WHERE id=?',
                (*[v for k,v in old_run.items() if k!='id'],ingest_id))
        print(json.dumps({'stage':'repair_company','company':items[0][0]['company_id'],'eligible':len(items),'attached':result.attached_listings},ensure_ascii=False),flush=True)
    with connect(master) as c:
        for row,outcome,detail,proof in decisions:
            c.execute('INSERT OR IGNORE INTO realpro_quality_repairs VALUES (?,?,?,?,?,?,?,?)',
                (REPAIR,row['ingest_run_id'],row['evidence_id'],row['classification'],row['reason'],outcome,detail,json.dumps(proof,ensure_ascii=False)))
        for key,original in originals.items():
            now=c.execute('SELECT * FROM buildings WHERE building_id=?',(key,)).fetchone()
            if now is None:raise ValueError('existing_building_removed')
            changed=[k for k in original if now[k]!=original[k]]
            if changed:c.execute('UPDATE buildings SET '+','.join('"'+k+'"=?' for k in changed)+' WHERE building_id=?',(*[original[k] for k in changed],key))
        if preservation_state(c,preserved[0])[1]!=preserved[1]:raise ValueError('existing_history_changed')
        if [tuple(r) for r in c.execute('SELECT * FROM current_ingest_snapshots ORDER BY source')]!=snapshots:raise ValueError('snapshot_changed')
        if {r['id']:dict(r) for r in c.execute('SELECT * FROM ingest_runs')}!=ingest:raise ValueError('input_run_changed')
        if [tuple(r) for r in c.execute('SELECT * FROM realpro_pdf_inputs ORDER BY sha256')]!=inputs:raise ValueError('pdf_input_changed')
        if [tuple(r) for r in c.execute('SELECT * FROM realpro_company_batches ORDER BY scope_key,semantic_hash')]!=batches:raise ValueError('batch_identity_changed')
        if {r['listing_key']:r for r in effective_rentals(c) if r['source_kind']=='ulucks'}!=ulucks:raise ValueError('ulucks_changed')
        after_rows=current_rows(c);after=counts(after_rows,private)
        new_ids={r[0] for r in c.execute('SELECT building_id FROM buildings')}-initial_ids
        if new_ids-{r['building_id'] for r in accepted}:raise ValueError('unadopted_building_seed')
        if len(after_rows)!=len(rows) or sum(before.values())!=sum(after.values()):raise ValueError('row_accounting_changed')
    area=apply_publication_scope(master,baseline)
    rebuild(str(master));validate_master(master)
    qc=validate_adopted_rows(master)
    public=work/'public.sqlite3'; public_counts=export_public(master,public,baseline=baseline)
    with readonly(baseline) as b,readonly(public) as c:
        if not {r[0] for r in b.execute('SELECT building_id FROM buildings')}<={r[0] for r in c.execute('SELECT building_id FROM buildings')}:raise ValueError('public_id_removed')
    public_ids=rendered_ids(public)
    proof=[]
    with readonly(master) as c:
        proof_ids=sorted({r['building_id'] for r in accepted}&public_ids)
        if not proof_ids:proof_ids=sorted(public_ids)[:3]
        for key in proof_ids:
            value=c.execute('SELECT building_key,vacancy_count,rent_yen_min,rent_yen_max,area_sqm_min,area_sqm_max,layout_types_json FROM building_summaries WHERE building_key=?',(key,)).fetchone()
            if value:
                value=dict(zip(('building_key','vacancy_count','rent_yen_min','rent_yen_max','area_sqm_min','area_sqm_max','layout_types_json'),value))
                value['layout_types']=json.loads(value.pop('layout_types_json') or '[]')
                fee=c.execute('SELECT maint_yen_min,maint_yen_max FROM building_rental_summaries WHERE building_key=?',(key,)).fetchone()
                if fee:value.update(zip(('maint_yen_min','maint_yen_max'),fee))
                proof.append(value)
    company=defaultdict(Counter)
    causes=defaultdict(Counter)
    for row in after_rows:company[row['company_id']][row['classification']]+=1
    for name,item in private_rows:company[name]['anomaly']+=1
    for row,outcome,detail,proof in decisions:causes[row['company_id']][detail]+=1
    reviewed={row['evidence_id']:detail for row,outcome,detail,proof in decisions if outcome=='held'}
    remaining=Counter(reviewed.get(r['evidence_id'],r['reason']) for r in after_rows if r['classification'] in ('held','anomaly'))
    remaining.update(item['reason'] for name,item in private_rows)
    before_causes=defaultdict(Counter)
    for row in rows:before_causes[row['company_id']][row['reason'] or 'accepted']+=1
    for name,item in private_rows:before_causes[name][item['reason']]+=1
    report=dict(source='realpro',integration_contract='realpro-partial-v1',acquisition_status='pdf_verified',
        collection_mode='existing_pdf_quality_repair',repair_version=REPAIR,parsed_rows=sum(before.values()),
        attached_rows=after.get('accepted_existing',0)+after.get('accepted_new',0),rescued_count=len(accepted),
        row_counts=after,row_counts_before=before,new_buildings=len(new_ids),proof=proof,
        pdf_count=len(expected),pdf_pages=inventory['pdf_pages'],newly_acquired_pdf_count=0,
        adopted_qc=qc,public_counts=public_counts,publication_area=area,historical_rows_preserved=True,
        other_snapshots_preserved=True,ulucks_preserved=True,pdf_inputs_unchanged=True,
        source_inventory=inventory,repair_causes={k:dict(v) for k,v in causes.items()},
        company_counts={k:dict(v) for k,v in company.items()},rescued_rows=accepted,
        company_causes_before={k:dict(v) for k,v in before_causes.items()},
        public_rescued_rows=sum(r['building_id'] in public_ids for r in accepted),
        public_rescued_buildings=len({r['building_id'] for r in accepted if r['building_id'] in public_ids}),
        remaining_reasons=dict(remaining))
    from tatemono_map.cloud.fetch_public import validate_collection_proof
    validate_collection_proof(report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bucket',required=True);p.add_argument('--zip',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True);p.add_argument('--source-commit',required=True)
    p.add_argument('--expected-generation',type=int,required=True);p.add_argument('--commit',action='store_true')
    a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True);store=GCSStore(a.bucket)
    head,generation=store.read_head()
    if generation!=a.expected_generation:raise ValueError('official_head_changed')
    manifest=a.work/'candidate.json'
    if not a.commit:
        run=new_run_id()
        # Never mutate a prior candidate or a downloaded official master.
        official=a.work/'original';official.mkdir(exist_ok=True)
        head,generation,backups=backup_current(store,official,run)
        if generation!=a.expected_generation:raise ValueError('official_head_changed')
        shutil.copy2(official/'master.sqlite3',a.work/'master.sqlite3')
        baseline=official/'baseline.sqlite3'
        report=repair_candidate(a.work/'master.sqlite3',baseline,a.zip,a.work,run)
        preserve_ulucks_catalog(store,head,run,report)
        report.update(backup_refs=backups,previous_head_generation=generation,previous_run_id=head['run_id'],
            original_manifest_ref=head['report']['original_manifest_ref'])
        manifest.write_text(json.dumps(dict(run_id=run,source_commit=a.source_commit,head_generation=generation,
            master_sha256=sha256(a.work/'master.sqlite3'),public_sha256=sha256(a.work/'public.sqlite3'),report=report),ensure_ascii=False))
        store.upload_verified(manifest,f'private-runs/{run}/realpro-quality-candidate.json')
        print('REALPRO_QUALITY_CANDIDATE='+json.dumps({k:report[k] for k in ['row_counts_before','row_counts','rescued_count','new_buildings','public_counts','public_rescued_rows','remaining_reasons']},ensure_ascii=False),flush=True)
        return
    candidate=json.loads(manifest.read_text())
    if candidate['head_generation']!=generation or candidate['source_commit']!=a.source_commit:raise ValueError('candidate_identity_changed')
    for kind in ('master','public'):
        if sha256(a.work/(kind+'.sqlite3'))!=candidate[kind+'_sha256']:raise ValueError('candidate_changed')
    validate_master(a.work/'master.sqlite3');validate_adopted_rows(a.work/'master.sqlite3')
    with store.collection_lease(candidate['run_id']):
        fresh,g=store.read_head()
        if g!=generation:raise ValueError('official_head_changed')
        result=commit_release(store,a.work,candidate['run_id'],generation,candidate['report'],a.source_commit)
    (a.work/'committed-head.json').write_text(json.dumps(result,ensure_ascii=False))
    print('REALPRO_QUALITY_COMMITTED='+result['run_id'],flush=True)


if __name__=='__main__':main()
