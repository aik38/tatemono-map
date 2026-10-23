"""Repeatable private PDF-batch ingestion; no provider login or scheduler changes.

Run with --zip FILE --bucket BUCKET --source-commit SHA [--commit]. The default
stages and validates a disposable master. Only --commit may CAS the official HEAD.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pdfplumber

from tatemono_map.cli.pdf_batch_run import (
    RealproParser, sha256_file, normalize_pdf_text, nfkc, write_master_import_csv,
    _is_area_listing_line,
)
from tatemono_map.building_registry.ingest_master_import import ingest_master_import_csv, set_current_snapshot
from tatemono_map.building_registry.normalization import normalize_building_input
from tatemono_map.cloud.partial import literal_room, review_key
from tatemono_map.cloud.pipeline import validate_master, preservation_state, digest
from tatemono_map.cloud.public_db import export_public, readonly, rendered_ids
from tatemono_map.cloud.storage import GCSStore, validate_head, commit_release, collection_run_id
from tatemono_map.cloud.run import new_run_id
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.normalize.effective_rentals import effective_rentals, canonical_key
from tatemono_map.ulucks_geography import municipality_of

PARSER_VERSION = 'realpro-batch-20261024-v2'
FUKUOKA_CITIES = ('北九州','福岡','大牟田','久留米','直方','飯塚','田川','柳川','八女','筑後','大川',
    '行橋','豊前','中間','小郡','筑紫野','春日','大野城','宗像','太宰府','古賀','福津','うきは',
    '宮若','嘉麻','朝倉','みやま','糸島','那珂川')
FUKUOKA_COUNTIES = ('糟屋','遠賀','鞍手','嘉穂','朝倉','三井','三潴','八女','田川','京都','築上')
TERMS = ('building_name','address','room','rent_man','fee_man','layout','area_sqm','availability_raw','built_year_month','structure')


def fukuoka_address(value):
    text = re.sub(r'\s+', '', nfkc(value))
    if text.startswith('福岡県'):
        text = text[3:]
    return any(text.startswith(c+'市') for c in FUKUOKA_CITIES) or any(text.startswith(c+'郡') for c in FUKUOKA_COUNTIES)


def inventory(pdf):
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    reader = pdfplumber.open(pdf)
    first = normalize_pdf_text(reader.pages[0].extract_text())
    # Header precedes the provider's office address, never a property's address.
    company = first.split('空室一覧表')[0]
    company = re.sub(r'^\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\s+現在\s*', '', company).strip()
    if not company or len(company)>180 or '空室一覧表' not in first:
        raise ValueError('unverified_company_title')
    tm = re.search(r'(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})', first)
    acquired = datetime.strptime(' '.join(tm.groups()),'%Y/%m/%d %H:%M:%S').isoformat()+'+09:00' if tm else None
    room_ids = {}
    for page_no, page in enumerate(reader.pages,1):
        ids=[]
        for annotation in page.annots:
            uri=annotation.get('uri','')
            parts=urlsplit(str(uri))
            if parts.path.endswith('/room_detail.php'):
                value=parse_qs(parts.query).get('id',[''])[0]
                if not value.isdigit(): raise ValueError('invalid_source_room_id')
                if value not in ids:ids.append(value)
        room_ids[page_no]=ids
    metadata={'filename':pdf.name,'sha256':sha256_file(pdf),'company':company,
        'acquired_at':acquired,'pages':len(reader.pages),'room_ids':room_ids}
    reader.close()
    return metadata


def parse_pdf(pdf, cache):
    hashed=sha256_file(pdf)
    cache.mkdir(parents=True,exist_ok=True)
    target=cache/(hashed+'.json')
    if target.exists():
        cached=json.loads(target.read_text())
        if (cached.get('parser_version')==PARSER_VERSION and
                cached['metadata']['sha256']==hashed and cached['metadata']['filename']==pdf.name):
            return cached
    metadata=inventory(pdf)
    parsed=RealproParser().parse(pdf)
    rows=json.loads(parsed.df.to_json(orient='records',force_ascii=False))
    errors=[]
    if not rows:errors.append('no_parsed_rooms')
    if len({r['evidence_id'] for r in rows})!=len(rows):errors.append('duplicate_evidence')
    for page_no,ids in metadata['room_ids'].items():
        page_rows=[r for r in rows if r['page']==page_no]
        if len(page_rows)!=len(ids):errors.append(f'page_{page_no}_source_rooms_{len(ids)}_parsed_{len(page_rows)}')
        else:
            for row,room_id in zip(page_rows,ids):row['source_room_id']=room_id
    for warning in set(parsed.warnings):
        if warning!='address_normalize_failed':errors.append(warning)
    result={'parser_version':PARSER_VERSION,'metadata':metadata,'rows':rows,
        'warnings':sorted(set(parsed.warnings)),'errors':errors}
    target.write_text(json.dumps(result,ensure_ascii=False))
    return result


def apply_publication_scope(master, baseline):
    """Persist area exclusions as ordinary hidden flags for older Ulucks images.

    Explicit pre-existing hides and all previous public IDs are preserved. Set
    cloud_publication_settings.area to fukuoka or all to expand this policy.
    """
    with readonly(baseline) as c:previous={r[0] for r in c.execute('SELECT building_id FROM buildings')}
    with connect(master) as c:
        c.execute('CREATE TABLE IF NOT EXISTS cloud_publication_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        c.execute("INSERT OR IGNORE INTO cloud_publication_settings VALUES ('area','kitakyushu')")
        c.execute('CREATE TABLE IF NOT EXISTS cloud_geographic_exclusions (building_id TEXT PRIMARY KEY, area TEXT NOT NULL)')
        area=c.execute("SELECT value FROM cloud_publication_settings WHERE key='area'").fetchone()[0]
        if area not in ('kitakyushu','fukuoka','all'):raise ValueError('invalid_publication_area')
        for key,address,hidden in c.execute('SELECT building_id,canonical_address,hidden_from_public FROM buildings').fetchall():
            excluded=c.execute('SELECT 1 FROM cloud_geographic_exclusions WHERE building_id=?',(key,)).fetchone()
            allowed=area=='all' or (fukuoka_address(address) if area=='fukuoka' else bool(municipality_of(address)))
            if allowed:
                if excluded:
                    c.execute('UPDATE buildings SET hidden_from_public=0 WHERE building_id=?',(key,))
                    c.execute('DELETE FROM cloud_geographic_exclusions WHERE building_id=?',(key,))
            elif key not in previous and (not hidden or excluded):
                c.execute('INSERT OR REPLACE INTO cloud_geographic_exclusions VALUES (?,?)',(key,area))
                c.execute('UPDATE buildings SET hidden_from_public=1 WHERE building_id=?',(key,))
    return area


def _schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS realpro_pdf_inputs (
        sha256 TEXT PRIMARY KEY, company TEXT NOT NULL, acquired_at TEXT, pages INTEGER NOT NULL,
        original_ref TEXT NOT NULL, parser_version TEXT NOT NULL, status TEXT NOT NULL,
        result_json TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS realpro_company_batches (
        scope_key TEXT NOT NULL, semantic_hash TEXT NOT NULL, ingest_run_id INTEGER NOT NULL,
        acquired_at TEXT, PRIMARY KEY(scope_key,semantic_hash))''')


def update_batch(master, inputs, work, run, baseline):
    validate_master(master)
    with connect(master) as c:
        _schema(c)
        initial={r['building_id']:dict(r) for r in c.execute('SELECT * FROM buildings')}
        before={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('buildings','listings','sale_listings','raw_sources')}
        preserved=preservation_state(c)
        snapshots=dict(c.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots'))
        ulucks={r['listing_key']:r for r in effective_rentals(c) if r['source_kind']=='ulucks'}
    totals=Counter(); results=[]; affected=set(); changed_scopes={}; parsed_total=0
    groups=defaultdict(list)
    for item in inputs:groups[item['metadata']['company']].append(item)
    for company,items in sorted(groups.items()):
        scope='realpro:batch:'+digest(company)[:32]
        rows=[]; invalid={}; exclusions={}; duplicates={}
        for item in items:
            meta=item['metadata']
            for raw in item['rows']:
                row=dict(raw)
                row['building_name']=re.sub(r'\s+'+re.escape(str(row['room']))+r'号室$', '',row['building_name']).strip()
                row['evidence_id']=f"realpro:{meta['sha256']}:{raw['evidence_id'].split('#',1)[-1]}"
                row['_pdf_sha256']=meta['sha256'];row['_company']=company
                rows.append(row)
                evidence=row['evidence_id']
                if item['errors']:invalid[evidence]='pdf_accounting_or_context_failed'
                elif not fukuoka_address(row['address']):exclusions[evidence]='outside_fukuoka'
                elif not row['building_name'] or _is_area_listing_line(row['building_name']):invalid[evidence]='invalid_building_name'
                elif '丁目丁目' in row['address']:invalid[evidence]='incomplete_source_address'
                elif literal_room(row['room']) is None:invalid[evidence]='ambiguous_room_label'
                elif not (row.get('rent_man') and row['rent_man']>0 and row.get('area_sqm') and row['area_sqm']>0):invalid[evidence]='invalid_rent_or_area'
        parsed_total+=len(rows)
        # Exact provider room IDs are stronger than name spellings. Conflicting
        # identities/terms stay private; no arbitrary "last row wins" choice.
        by_id=defaultdict(list)
        for row in rows:
            if row['evidence_id'] not in invalid.keys()|exclusions.keys():
                by_id[row.get('source_room_id') or (row['building_name'],row['address'],row['room'])].append(row)
        for same in by_id.values():
            if len(same)>1:
                terms={digest({k:r.get(k) for k in TERMS}) for r in same}
                for row in same[1:] if len(terms)==1 else same:
                    (duplicates if len(terms)==1 else invalid)[row['evidence_id']]='identical_source_room' if len(terms)==1 else 'conflicting_source_room'
        by_identity=defaultdict(list)
        for row in rows:
            if row['evidence_id'] not in invalid.keys()|exclusions.keys()|duplicates.keys():
                n=normalize_building_input(row['building_name'],row['address'])
                by_identity[(n.normalized_name,n.normalized_address,literal_room(row['room']))].append(row)
        for same in by_identity.values():
            if len(same)>1:
                terms={digest({k:r.get(k) for k in TERMS if k not in ('building_name','address')}) for r in same}
                for row in same[1:] if len(terms)==1 else same:
                    (duplicates if len(terms)==1 else invalid)[row['evidence_id']]='identical_provider_unit' if len(terms)==1 else 'conflicting_provider_unit'
        valid=[r for r in rows if r['evidence_id'] not in invalid.keys()|exclusions.keys()|duplicates.keys()]
        semantic=digest(sorted(digest({k:r.get(k) for k in TERMS}) for r in valid))
        acquired=max((i['metadata']['acquired_at'] or '' for i in items),default='')
        with connect(master) as c:
            seen=c.execute('SELECT ingest_run_id FROM realpro_company_batches WHERE scope_key=? AND semantic_hash=?',(scope,semantic)).fetchone()
            old=c.execute('''SELECT DISTINCT l.listing_key,l.building_key,l.room_label FROM listings l
                JOIN ingest_runs r ON r.id=l.ingest_run_id WHERE l.source_kind='realpro' AND
                ((r.source=? AND l.ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots))
                OR EXISTS(SELECT 1 FROM cloud_retained_listings h JOIN current_ingest_snapshots s
                ON h.scope_key=s.source AND h.ingest_run_id=s.ingest_run_id
                WHERE h.listing_key=l.listing_key AND h.scope_key=?))''',(scope,scope)).fetchall()
        if seen:
            company_result={'company':company,'status':'duplicate_content','parsed_rows':len(rows),'ingest_run_id':seen[0]}
            totals['duplicate']+=len(rows)
        elif not valid:
            for r in rows:totals['anomaly' if r['evidence_id'] in invalid else 'duplicate' if r['evidence_id'] in duplicates else 'held']+=1
            company_result={'company':company,'status':'private_no_valid_rows','parsed_rows':len(rows),
                'outside_fukuoka':len(exclusions),'row_results':[
                    {'evidence_id':r['evidence_id'],'reason':invalid.get(r['evidence_id']) or exclusions.get(r['evidence_id']) or duplicates.get(r['evidence_id'])} for r in rows]}
        else:
            csv=work/('import-'+digest(company)[:12]+'.csv')
            write_master_import_csv(pd.DataFrame(valid),csv)
            imported=ingest_master_import_csv(str(master),str(csv),source='realpro',snapshot_source=scope,
                snapshot_key=semantic,auto_seed_high_confidence=True,strict_name_match=True)
            counts=Counter(); retained=0
            with connect(master) as c:
                offers={r['listing_key']:dict(r) for r in c.execute('SELECT * FROM listings WHERE ingest_run_id=?',(imported.ingest_run_id,))}
                queued={r['evidence_id']:r['reason'] for r in c.execute('SELECT evidence_id,reason FROM unmatched_queue WHERE ingest_run_id=?',(imported.ingest_run_id,))}
                # Link using the unchanged importer key calculation on the CSV's
                # string values, not floating-point JSON representation.
                import csv as csv_module
                from tatemono_map.building_registry.ingest_master_import import _listing_key
                with csv.open(encoding='utf-8-sig',newline='') as stream:
                    keyed={r['evidence_id']:hashlib.sha256(f'{imported.ingest_run_id}:{_listing_key(r)}'.encode()).hexdigest() for r in csv_module.DictReader(stream)}
                accepted={e:offers[k] for e,k in keyed.items() if k in offers}
                aliases=dict(c.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
                units=defaultdict(list)
                for e,r in accepted.items():units[(canonical_key(r['building_key'],aliases),literal_room(r['room_label']))].append((e,r))
                for group in units.values():
                    if len(group)>1:
                        terms={tuple(r.get(k) for k in ('rent_yen','maint_yen','layout','area_sqm','availability_raw')) for e,r in group}
                        for e,r in group[1:] if len(terms)==1 else group:
                            c.execute('DELETE FROM listings WHERE listing_key=? AND ingest_run_id=?',(r['listing_key'],imported.ingest_run_id))
                            accepted.pop(e)
                            (duplicates if len(terms)==1 else invalid)[e]='identical_canonical_unit' if len(terms)==1 else 'conflicting_canonical_unit'
                fresh={(canonical_key(r['building_key'],aliases),literal_room(r['room_label'])) for r in accepted.values()}
                for row in rows:
                    e=row['evidence_id']; offer=accepted.get(e)
                    classification='accepted_existing' if offer and offer['building_key'] in initial else 'accepted_new' if offer else 'anomaly' if e in invalid else 'duplicate' if e in duplicates else 'held'
                    reason=invalid.get(e) or duplicates.get(e) or exclusions.get(e) or queued.get(e) or ''
                    if not offer and not reason:raise ValueError('unaccounted_realpro_row')
                    counts[classification]+=1
                    c.execute('INSERT INTO cloud_collection_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(
                        scope,imported.ingest_run_id,e,company,review_key(scope,row['building_name'],row['address'],row['room']),classification,
                        offer['building_key'] if offer else None,row['room'],json.dumps(row,ensure_ascii=False),reason,'[]',offer['listing_key'] if offer else None))
                # A batch is not a company-wide deletion instruction. Retain
                # every previously known unit absent from the new supplied PDF.
                for listing,building,room in old:
                    if (canonical_key(building,aliases),literal_room(room)) not in fresh:
                        c.execute('INSERT OR IGNORE INTO cloud_retained_listings VALUES (?,?,?,?)',(listing,scope,imported.ingest_run_id,'not_observed_in_supplied_pdf'))
                        retained+=1
                for listing,building,room in c.execute('''SELECT listing_key,building_key,room_label FROM listings
                    WHERE source_kind='realpro' AND ingest_run_id<>? AND ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots)''',(imported.ingest_run_id,)).fetchall():
                    if (canonical_key(building,aliases),literal_room(room)) in fresh:
                        c.execute('INSERT OR IGNORE INTO cloud_unit_overlaps VALUES (?,?,?)',(listing,scope,imported.ingest_run_id))
                set_current_snapshot(c,scope,imported.ingest_run_id)
                c.execute('INSERT INTO realpro_company_batches VALUES (?,?,?,?)',(scope,semantic,imported.ingest_run_id,acquired))
                affected.update(r['building_key'] for r in accepted.values())
                changed_scopes[scope]=imported.ingest_run_id
            totals.update(counts)
            company_result={'company':company,'status':'integrated_private_candidate','parsed_rows':len(rows),
                'row_counts':dict(counts),'outside_fukuoka':len(exclusions),'retained':retained,'ingest_run_id':imported.ingest_run_id}
        for item in items:
            m=item['metadata']
            result={**company_result,'filename':m['filename'],'sha256':m['sha256'],'pages':m['pages'],
                'pdf_parsed_rows':len(item['rows']),'parser_errors':item['errors'],'warnings':item['warnings']}
            results.append(result)
            with connect(master) as c:
                c.execute('INSERT OR IGNORE INTO realpro_pdf_inputs VALUES (?,?,?,?,?,?,?,?)',(
                    m['sha256'],company,m['acquired_at'],m['pages'],json.dumps(m['gcs_ref']),PARSER_VERSION,result['status'],json.dumps(result,ensure_ascii=False)))
        print(json.dumps({'stage':'company_candidate','company':company,'parsed':len(rows),'result':company_result},ensure_ascii=False),flush=True)
    with connect(master) as c:
        # The existing importer refreshes some shared building attributes. A
        # lower-priority source must leave every adopted canonical row intact.
        for key,original in initial.items():
            current=c.execute('SELECT * FROM buildings WHERE building_id=?',(key,)).fetchone()
            if current is None:raise ValueError('existing_building_removed')
            changed=[k for k in original if current[k]!=original[k]]
            if changed:c.execute('UPDATE buildings SET '+','.join('"'+k+'"=?' for k in changed)+' WHERE building_id=?',(*[original[k] for k in changed],key))
        if preservation_state(c,preserved[0])[1]!=preserved[1]:raise ValueError('existing_history_or_alias_changed')
        if dict(c.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots WHERE source NOT IN ('+','.join('?' for _ in changed_scopes)+')',tuple(changed_scopes))) != {k:v for k,v in snapshots.items() if k not in changed_scopes}:
            raise ValueError('other_snapshots_changed')
        effective={r['listing_key']:r for r in effective_rentals(c) if r['source_kind']=='ulucks'}
        if effective!=ulucks:raise ValueError('ulucks_effective_rows_changed')
        if c.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('foreign_key_error')
    area=apply_publication_scope(master,baseline)
    rebuild(str(master));validate_master(master)
    adopted_qc=validate_adopted_rows(master)
    public_counts=export_public(master,work/'public.sqlite3',baseline=baseline)
    public_ids=rendered_ids(work/'public.sqlite3')
    with readonly(master) as c:
        after={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in before}
        proof=[]
        for key in sorted(affected & public_ids):
            value=c.execute('SELECT building_key,vacancy_count,rent_yen_min,rent_yen_max,area_sqm_min,area_sqm_max,layout_types_json FROM building_summaries WHERE building_key=?',(key,)).fetchone()
            if value:
                value=dict(zip(('building_key','vacancy_count','rent_yen_min','rent_yen_max','area_sqm_min','area_sqm_max','layout_types_json'),value))
                value['layout_types']=json.loads(value.pop('layout_types_json') or '[]')
                fee=c.execute('SELECT maint_yen_min,maint_yen_max FROM building_rental_summaries WHERE building_key=?',(key,)).fetchone()
                if fee:value.update(zip(('maint_yen_min','maint_yen_max'),fee))
                proof.append(value)
        new_ids={r[0] for r in c.execute('SELECT building_id FROM buildings')}-initial.keys()
        adopted={r[0] for r in c.execute('SELECT DISTINCT building_key FROM listings')}
        if new_ids-adopted:raise ValueError('unadopted_new_canonical_building')
    with readonly(work/'public.sqlite3') as c,readonly(baseline) as b:
        previous={r[0] for r in b.execute('SELECT building_id FROM buildings')}
        for key,address in c.execute('SELECT building_id,canonical_address FROM buildings'):
            if key not in previous and area=='kitakyushu' and not municipality_of(address):raise ValueError('public_geography_leak')
    if sum(totals.values())!=parsed_total:raise ValueError('batch_accounting_failed')
    if not proof and totals['accepted_new']+totals['accepted_existing']:raise ValueError('no_public_realpro_proof')
    return {'source':'realpro','integration_contract':'realpro-partial-v1','acquisition_status':'pdf_verified',
        'collection_mode':'supplied_pdf_batch','parsed_rows':parsed_total,'attached_rows':totals['accepted_new']+totals['accepted_existing'],
        'row_counts':dict(totals),'new_buildings':after['buildings']-before['buildings'],'counts_before':before,'counts_after':after,
        'pdf_count':len(inputs),'pdf_pages':sum(i['metadata']['pages'] for i in inputs),'public_counts':public_counts,
        'publication_area':area,'adopted_qc':adopted_qc,'historical_rows_preserved':True,'other_snapshots_preserved':True,'ulucks_preserved':True,
        'proof':proof,'company_results':results,'processed_at':datetime.now(timezone.utc).isoformat()}



def validate_adopted_rows(master):
    """Compare adopted private rows with their source evidence and selection."""
    from decimal import Decimal
    with readonly(master) as c:
        c.row_factory = __import__('sqlite3').Row
        rows=c.execute("""SELECT q.raw_json,q.listing_key FROM cloud_collection_rows q
            JOIN current_ingest_snapshots s ON s.source=q.scope_key AND s.ingest_run_id=q.ingest_run_id
            WHERE q.scope_key LIKE 'realpro:batch:%'
              AND q.classification IN ('accepted_existing','accepted_new')""").fetchall()
        checked=0; adopted_keys=set()
        for evidence,key in rows:
            raw=json.loads(evidence)
            listing=c.execute('SELECT * FROM listings WHERE listing_key=?',(key,)).fetchone()
            if listing is None:raise ValueError('adopted_listing_missing')
            if not fukuoka_address(raw['address']):raise ValueError('adopted_outside_fukuoka')
            if listing['rent_yen']!=int(Decimal(str(raw['rent_man']))*10000):raise ValueError('adopted_rent_differs_from_pdf')
            fee=raw.get('fee_man')
            expected_fee=None if fee is None else int(Decimal(str(fee))*10000)
            if listing['maint_yen']!=expected_fee:raise ValueError('adopted_fee_differs_from_pdf')
            if abs(listing['area_sqm']-raw['area_sqm'])>0.000001:raise ValueError('adopted_area_differs_from_pdf')
            if literal_room(listing['room_label'])!=literal_room(raw['room']):raise ValueError('adopted_room_differs_from_pdf')
            incoming=normalize_building_input(raw['building_name'],raw['address'])
            stored=normalize_building_input(listing['name'],listing['address'])
            if (incoming.normalized_name,incoming.normalized_address)!=(stored.normalized_name,stored.normalized_address):
                raise ValueError('adopted_source_identity_differs_from_pdf')
            checked+=1;adopted_keys.add(key)
        by_building=defaultdict(list)
        for listing in effective_rentals(c):by_building[listing['building_key']].append(listing)
        effective=0
        for building,listings in by_building.items():
            if any(r['source_kind']=='ulucks' for r in listings) and any(r['source_kind']=='realpro' and r['listing_key'] in adopted_keys for r in listings):
                raise ValueError('realpro_selected_alongside_ulucks')
            units=defaultdict(list)
            for listing in listings:
                if listing['source_kind']=='realpro':
                    units[literal_room(listing['room_label'])].append(listing['listing_key'])
                    effective+=listing['listing_key'] in adopted_keys
            for keys in units.values():
                if len(keys)>1 and any(k in adopted_keys for k in keys):raise ValueError('duplicate_effective_realpro_unit')
    return {'adopted_evidence_rows_checked':checked,'effective_adopted_rows':effective}


def backup_current(store,work,run):
    head,generation=store.read_head();validate_head(head)
    backup_prefix=f'deployment-backups/realpro/{run}'
    hp=work/'previous-head.json';hp.write_text(json.dumps(head))
    refs={'head':store.upload_verified(hp,backup_prefix+'/head.json')}
    for kind,filename in (('master','master.sqlite3'),('public','baseline.sqlite3')):
        path=work/filename
        # A cached byte-identical immutable object is the current generation's
        # content, not a restoration of an older release. Always compare against
        # the freshly read official reference and create a fresh pinned backup.
        if not path.exists() or sha256_file(path)!=head[kind]['sha256']:
            store.download(head[kind],path)
        if kind=='master':validate_master(path)
        else:
            from tatemono_map.cloud.public_db import validate_public
            validate_public(path)
        refs[kind]=store.clone_verified(head[kind],backup_prefix+'/'+kind+'.sqlite3')
    receipt=work/'backup-receipt.json';receipt.write_text(json.dumps({'head_generation':generation,'previous_run':head['run_id'],'refs':refs}))
    store.upload_verified(receipt,backup_prefix+'/receipt.json')
    return head,generation,refs


def preserve_ulucks_catalog(store, previous_head, run, report):
    """Carry the last verified Ulucks census across a RealPro-only release."""
    previous_report=previous_head['report']
    reference=previous_report.get('company_catalog_ref')
    if reference is None:return
    previous_run=collection_run_id(previous_head)
    if reference.get('object')!=f'private-runs/{previous_run}/company-catalog.json':
        raise ValueError('previous_company_catalog_reference_invalid')
    report['company_catalog_ref']=store.clone_verified(reference,f'private-runs/{run}/company-catalog.json')
    report['company_ids']=list(previous_report.get('company_ids',[]))
    report['inherited_ulucks_collection_run_id']=previous_report.get('inherited_ulucks_collection_run_id',previous_run)


def execute(store,zip_path,work,source_commit,*,commit=False,expected_pdfs=None):
    work.mkdir(parents=True,exist_ok=True);run=new_run_id()
    archive_sha=sha256_file(zip_path)
    # Preserve each original separately; no second archive upload is needed.
    archive_ref={'sha256':archive_sha,'filename':zip_path.name}
    pdf_dir=work/'originals';pdf_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        names=[n for n in archive.namelist() if n.lower().endswith('.pdf')]
        if expected_pdfs is not None and len(names)!=expected_pdfs:raise ValueError('pdf_input_count_mismatch')
        if len({Path(n).name for n in names})!=len(names):raise ValueError('duplicate_input_filename')
        for name in names:
            if archive.getinfo(name).file_size>100*1024*1024:raise ValueError('oversized_pdf')
            (pdf_dir/Path(name).name).write_bytes(archive.read(name))
    # Select only this archive's files when reusing a work directory. Preserve
    # every original before any parser can fail, independently of integration.
    pdfs=sorted(pdf_dir/Path(name).name for name in names)
    original_refs={}
    for pdf in pdfs:
        hashed=sha256_file(pdf)
        original_refs[pdf]=store.upload_verified(pdf,f'private-inputs/realpro/originals/{hashed}/{pdf.name}')
    inputs=[]
    for pdf in pdfs:
        ref=original_refs[pdf];hashed=ref['sha256']
        analysis_path=work/'parsed'/(hashed+'.json')
        try:
            item=parse_pdf(pdf,work/'parsed')
        except Exception as exc:
            item={'parser_version':PARSER_VERSION,'metadata':{'filename':pdf.name,'sha256':hashed,
                'company':None,'acquired_at':None,'pages':None},'rows':[],'warnings':[],
                'errors':['parse_failed:'+type(exc).__name__]}
            analysis_path.parent.mkdir(parents=True,exist_ok=True)
            analysis_path.write_text(json.dumps(item,ensure_ascii=False))
        analysis_ref=store.upload_verified(analysis_path,f'private-inputs/realpro/analysis/{PARSER_VERSION}/{hashed}/{pdf.name}.json')
        item['metadata'].update(gcs_ref=ref,analysis_ref=analysis_ref);inputs.append(item)
        print(json.dumps({'stage':'pdf_preserved_parsed','file':pdf.name,'pages':item['metadata']['pages'],
            'rows':len(item['rows']),'errors':item['errors']},ensure_ascii=False),flush=True)
    if len(inputs)!=len(names):raise ValueError('batch_input_accounting_failed')
    manifest=work/'original-manifest.json'
    manifest.write_text(json.dumps({'archive_ref':archive_ref,'pdfs':[i['metadata'] for i in inputs]},ensure_ascii=False))
    manifest_ref=store.upload_verified(manifest,f'private-runs/{run}/original-manifest.json')
    if any(i['errors'] for i in inputs):raise ValueError('pdf_source_accounting_or_context_failed')
    # Input preservation/parse never takes the shared collection lock.
    with store.collection_lease(run):
        head,generation,backups=backup_current(store,work,run)
        report=update_batch(work/'master.sqlite3',inputs,work,run,work/'baseline.sqlite3')
        report.update(original_manifest_ref=manifest_ref,backup_refs=backups,newly_acquired_pdf_count=0)
        preserve_ulucks_catalog(store,head,run,report)
        output=work/'report.json';output.write_text(json.dumps(report,ensure_ascii=False))
        store.upload_verified(output,f'private-runs/{run}/realpro-report.json')
        if commit:
            if not report['attached_rows']:return {'status':'no_new_content','run_id':head['run_id']}
            commit_release(store,work,run,generation,report,source_commit)
        return {'status':'committed' if commit else 'validated_candidate','run_id':run,
            **{k:report[k] for k in ('counts_before','counts_after','row_counts','public_counts','pdf_count','pdf_pages')}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',type=Path,required=True);parser.add_argument('--bucket',required=True)
    parser.add_argument('--work',type=Path,required=True);parser.add_argument('--source-commit',required=True)
    parser.add_argument('--expected-pdfs',type=int);parser.add_argument('--commit',action='store_true')
    args=parser.parse_args()
    print('REALPRO_BATCH_RESULT='+json.dumps(execute(GCSStore(args.bucket),args.zip,args.work,args.source_commit,
        commit=args.commit,expected_pdfs=args.expected_pdfs),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
