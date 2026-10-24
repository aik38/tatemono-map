"""Integrate only complete MR scopes into a disposable, latest master copy."""
from __future__ import annotations
import csv
import hashlib
import json
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from tatemono_map.cloud.mansion_geography import municipality
from tatemono_map.cloud.pipeline import validate_master,preservation_state,digest
from tatemono_map.cloud.public_db import readonly,export_public,validate_public,sha256,rendered_ids
from tatemono_map.cloud.storage import validate_head,commit_release
from tatemono_map.cloud.realpro_weekly import save_json
from tatemono_map.cloud.realpro_batch import preserve_ulucks_catalog,apply_publication_scope
from tatemono_map.cloud.batch import public_proof
from tatemono_map.building_registry.ingest_master_import import MASTER_COLUMNS,ingest_master_import_csv,set_current_snapshot
from tatemono_map.building_registry.normalization import normalize_building_input
from tatemono_map.normalize.effective_rentals import effective_rentals,canonical_key,room_identity
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.db.repo import connect


def backup(store,work,run):
    head,generation=store.read_head();validate_head(head)
    refs={};prefix=f'deployment-backups/mansion-review/{run}'
    refs['head']=save_json(store,work,prefix+'/head.json',head)
    for key,file in [('master','master.sqlite3'),('public','baseline.sqlite3')]:
        store.download(head[key],work/file)
        (validate_master if key=='master' else validate_public)(work/file)
        refs[key]=store.clone_verified(head[key],prefix+'/'+key+'.sqlite3')
        # Download the copy, not just its source, to prove restore bytes.
        check=work/'restore-check.sqlite3';store.download(refs[key],check);check.unlink()
    receipt={'head_generation':generation,'previous_release':head['run_id'],'refs':refs,'restorable':True}
    save_json(store,work,prefix+'/receipt.json',receipt)
    return head,generation,refs


def schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS mansion_review_building_bindings (
        source_url TEXT PRIMARY KEY,building_id TEXT NOT NULL,normalized_address TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mansion_review_scopes (
        scope_key TEXT PRIMARY KEY, municipality TEXT NOT NULL, kind TEXT NOT NULL,
        ingest_run_id INTEGER NOT NULL, cycle TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mansion_review_rows (
        scope_key TEXT,ingest_run_id INTEGER,evidence_id TEXT,classification TEXT,reason TEXT,
        building_id TEXT,listing_key TEXT,raw_json TEXT,PRIMARY KEY(scope_key,ingest_run_id,evidence_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS mansion_review_sale_ownership (
        listing_key TEXT PRIMARY KEY,scope_key TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mansion_review_sale_buildings (
        building_id TEXT PRIMARY KEY,scope_key TEXT NOT NULL)''')


def master_row(row,evidence,now):
    r={k:'' for k in MASTER_COLUMNS}
    r.update(page=row['source_url'] or row['building_url'],category=row['kind'],updated_at=now,
        building_name=row['building_name'],room=row['room'],address=row['address'],
        rent_man=str(row['price_yen']/10000),fee_man='' if row['fee_yen'] is None else str(row['fee_yen']/10000),
        floor=row['floor'],layout=row['layout'],area_sqm=str(row['area_sqm']),built_raw=row['built_raw'],
        structure=row['structure'],structure_raw=row['structure'],evidence_id=evidence)
    labels={'交通':row['access'],'階建て':row['floor_count'],'総戸数':row['total_units'],
        '敷金':row['deposit'],'礼金':row['key_money'],'所在階':row['floor'],'向き':row['direction'],
        '詳細URL':row['source_url'],'建物URL':row['building_url'],'一覧URL':row['page_url']}
    r['raw_block']=' | '.join(k+':'+str(v) for k,v in labels.items() if v)+' | 原文:'+row['raw']
    return r


def update(master,acquisition,work,run,baseline):
    validate_master(master)
    with connect(master) as c:
        schema(c)
        initial={r['building_id']:dict(r) for r in c.execute('SELECT * FROM buildings')}
        before={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('buildings','listings','sale_listings','raw_sources')}
        preserved=preservation_state(c)
        snapshots=dict(c.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots'))
        protected={r['listing_key']:r for r in effective_rentals(c) if r['source_kind'] in ('ulucks','realpro')}
        old_aliases={r['alias_key']:dict(r) for r in c.execute('SELECT * FROM building_key_aliases')}
    totals=Counter();scope_results=[];changed={};affected=set();now=datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M:%S')
    for result in acquisition['results']:
        kind=result['kind'];name=result['municipality']
        if result['status'] not in ('success','confirmed_zero'):
            scope_results.append({k:v for k,v in result.items() if k not in ('rows','pages')});continue
        scope='mansion_review:'+kind+':'+result['city_id'];table='listings' if kind=='chintai' else 'sale_listings'
        keycol='listing_key' if kind=='chintai' else 'sale_listing_key';sourcecol='source_kind' if kind=='chintai' else 'source'
        source='mansion_review_'+kind
        rows=result['rows'];prepared=[];reasons={};observations={}
        with connect(master) as c:
            bindings={r[0]:(r[1],r[2]) for r in c.execute('SELECT * FROM mansion_review_building_bindings')}
            existing_aliases=dict(c.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
        new_aliases={}
        for i,row in enumerate(rows):
            e=row['evidence_id']+'#cycle='+acquisition['cycle']+'#observation='+str(i)
            observations[e]=row
            reason=row.get('reason','')
            n=normalize_building_input(row['building_name'],row['address'])
            binding=bindings.get(row['building_url'])
            if not reason and binding:
                from tatemono_map.building_registry.keys import make_alias_key
                alias=make_alias_key(n.normalized_name,n.normalized_address)
                if binding[1]!=n.normalized_address or (alias in existing_aliases and existing_aliases[alias]!=binding[0]):
                    reason='provider_building_identity_conflict'
                else:new_aliases[alias]=binding[0]
            # The old MR importer permits town-only auto seeds. A new canonical
            # asset must have a complete lot; coarse addresses may match only
            # an exact pre-existing identity. Never seed from a town alone.
            import re
            complete=bool(re.fullmatch(r'[^\d、〜]+\d+(?:-\d+){1,2}',n.normalized_address))
            exact=any(v['norm_name']==n.normalized_name and v['norm_address']==n.normalized_address for v in initial.values())
            if not reason and not (complete or exact or binding):reason='coarse_address_requires_review'
            if reason:reasons[e]=reason
            else:prepared.append(master_row(row,e,now))
        with connect(master) as c:
            for alias,bid in new_aliases.items():
                c.execute('INSERT OR IGNORE INTO building_key_aliases(alias_key,canonical_key) VALUES (?,?)',(alias,bid))
        path=work/'scope-import.csv'
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=MASTER_COLUMNS);writer.writeheader();writer.writerows(prepared)
        imported=ingest_master_import_csv(str(master),str(path),source='mansion_review',snapshot_source=scope,
            snapshot_key=acquisition['cycle']+':'+digest(rows),auto_seed_high_confidence=True,strict_name_match=True,exact_name_match=True)
        rid=imported.ingest_run_id;counts=Counter()
        with connect(master) as c:
            aliases=dict(c.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
            # Rental rows have no evidence column, so join using the importer's
            # deterministic listing key to avoid a building-wide cross join.
            from tatemono_map.building_registry.ingest_master_import import _listing_key
            accepted={}
            for pr in prepared:
                key=hashlib.sha256(f"{rid}:{_listing_key(pr)}".encode()).hexdigest()
                offer=c.execute(f'SELECT * FROM {table} WHERE {keycol}=? AND ingest_run_id=?',(key,rid)).fetchone()
                if offer and offer['building_key']:accepted[pr['evidence_id']]=dict(offer)
            source_buildings=defaultdict(set)
            for e,offer in accepted.items():source_buildings[observations[e]['building_url']].add(offer['building_key'])
            for e in list(accepted):
                if len(source_buildings[observations[e]['building_url']])>1:
                    c.execute(f'DELETE FROM {table} WHERE {keycol}=? AND ingest_run_id=?',(accepted[e][keycol],rid))
                    reasons[e]='provider_building_identity_conflict';accepted.pop(e)
            groups=defaultdict(list)
            for e,offer in accepted.items():
                row=observations[e];bid=canonical_key(offer['building_key'],aliases)
                identity=('room',room_identity(row['room'])) if room_identity(row['room']) else ('anonymous',row['floor'],row['price_yen'],row['area_sqm'],row['layout'],row['direction'])
                groups[(bid,identity)].append(e)
            for group in groups.values():
                if len(group)<=1:continue
                terms={tuple(observations[e][k] for k in ('price_yen','area_sqm','layout','floor','direction')) for e in group}
                # Conflicting explicit units are all held; identical anonymous
                # advertisements count once and retain all source evidence.
                discard=group[1:] if len(terms)==1 else group
                for e in discard:
                    c.execute(f'DELETE FROM {table} WHERE {keycol}=? AND ingest_run_id=?',(accepted[e][keycol],rid))
                    reasons[e]='duplicate_advertisement' if len(terms)==1 else 'conflicting_unit_terms';accepted.pop(e)
            fresh_buildings={canonical_key(v['building_key'],aliases) for v in accepted.values()}
            # Claim only the successfully fetched municipality/domain. Legacy
            # MR rows elsewhere (including every failed scope) remain active.
            old=c.execute(f'''SELECT s.{keycol},s.building_key,b.canonical_address,s.ingest_run_id FROM {table} s
                JOIN buildings b ON b.building_id=s.building_key WHERE s.{sourcecol}=? AND s.ingest_run_id<>?''',(source,rid)).fetchall()
            for key,bid,address,old_run in old:
                if municipality(address)!=name:continue
                if kind=='chintai':
                    if canonical_key(bid,aliases) in fresh_buildings:
                        c.execute('INSERT OR IGNORE INTO cloud_baseline_ownership VALUES (?,?)',(key,scope))
                    else:
                        # No fresh advertisement is not proof of zero vacancies.
                        # Retain only previously active MR rows; never revive a
                        # historical snapshot simply because it exists.
                        active=c.execute('SELECT 1 FROM current_ingest_snapshots WHERE ingest_run_id=?',(old_run,)).fetchone()
                        retained=c.execute('''SELECT 1 FROM cloud_retained_listings h JOIN current_ingest_snapshots s
                            ON s.source=h.scope_key AND s.ingest_run_id=h.ingest_run_id WHERE h.listing_key=?''',(key,)).fetchone()
                        if active or retained:c.execute('INSERT OR IGNORE INTO cloud_retained_listings VALUES (?,?,?,?)',(key,scope,rid,'mansion_not_observed_zero_unconfirmed'))
                else:
                    c.execute('INSERT OR IGNORE INTO mansion_review_sale_ownership VALUES (?,?)',(key,scope))
                    c.execute('INSERT OR IGNORE INTO mansion_review_sale_buildings VALUES (?,?)',(bid,scope))
                affected.add(bid)
            for e,row in observations.items():
                offer=accepted.get(e);reason=reasons.get(e,'unresolved_canonical_match' if not offer else '')
                cls=('accepted_existing' if offer['building_key'] in initial else 'accepted_new') if offer else ('duplicate' if reason=='duplicate_advertisement' else 'anomaly' if reason in ('invalid_row_context','numeric_out_of_range','conflicting_unit_terms','provider_building_identity_conflict') else 'held')
                counts[cls]+=1
                c.execute('INSERT INTO mansion_review_rows VALUES (?,?,?,?,?,?,?,?)',(scope,rid,e,cls,reason,
                    offer['building_key'] if offer else None,offer[keycol] if offer else None,json.dumps(row,ensure_ascii=False)))
                if offer:
                    affected.add(offer['building_key'])
                    n=normalize_building_input(row['building_name'],row['address'])
                    c.execute('INSERT OR IGNORE INTO mansion_review_building_bindings VALUES (?,?,?)',
                        (row['building_url'],offer['building_key'],n.normalized_address))
                    # Persist real listing URLs, not file:scope-import.csv.
                    c.execute(f'UPDATE {table} SET source_url=? WHERE {keycol}=?',(row['source_url'],offer[keycol]))
                    if kind=='mansion':
                        c.execute('INSERT OR IGNORE INTO mansion_review_sale_buildings VALUES (?,?)',(offer['building_key'],scope))
            set_current_snapshot(c,scope,rid)
            c.execute('INSERT OR REPLACE INTO mansion_review_scopes VALUES (?,?,?,?,?)',(scope,name,kind,rid,acquisition['cycle']))
            changed[scope]=rid
        totals.update(counts)
        summary={'scope_key':scope,'municipality':name,'kind':kind,'status':result['status'],'parsed_rows':len(rows),'row_counts':dict(counts),'ingest_run_id':rid}
        scope_results.append(summary);print(json.dumps({'stage':'mansion_integrated_scope',**summary},ensure_ascii=False),flush=True)
    with connect(master) as c:
        # A lower-priority source cannot rewrite adopted canonical attributes,
        # prior alias rows, histories, or the two protected source snapshots.
        for key,original in initial.items():
            current=c.execute('SELECT * FROM buildings WHERE building_id=?',(key,)).fetchone()
            if not current:raise ValueError('mansion_existing_building_removed')
            cols=[k for k in original if current[k]!=original[k]]
            if cols:c.execute('UPDATE buildings SET '+','.join('"'+k+'"=?' for k in cols)+' WHERE building_id=?',(*[original[k] for k in cols],key))
        for key,old in old_aliases.items():
            current=c.execute('SELECT * FROM building_key_aliases WHERE alias_key=?',(key,)).fetchone()
            if not current or current['canonical_key']!=old['canonical_key']:raise ValueError('mansion_existing_alias_retargeted')
            if dict(current)!=old:c.execute('UPDATE building_key_aliases SET updated_at=? WHERE alias_key=?',(old['updated_at'],key))
        if preservation_state(c,preserved[0])[1]!=preserved[1]:raise ValueError('mansion_existing_history_changed')
        current=dict(c.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots'))
        if any(current.get(k)!=v for k,v in snapshots.items() if k not in changed):raise ValueError('mansion_other_snapshot_changed')
        effective={r['listing_key']:r for r in effective_rentals(c) if r['source_kind'] in ('ulucks','realpro')}
        if effective!=protected:raise ValueError('mansion_ulucks_realpro_changed')
        for bid, in c.execute('SELECT building_id FROM buildings').fetchall():
            if bid not in initial and not c.execute('SELECT 1 FROM listings WHERE building_key=? UNION ALL SELECT 1 FROM sale_listings WHERE building_key=?',(bid,bid)).fetchone():
                c.execute('UPDATE buildings SET hidden_from_public=1 WHERE building_id=?',(bid,))
    area=apply_publication_scope(master,baseline)
    rebuild(str(master));validate_master(master)
    counts=export_public(master,work/'public.sqlite3',baseline=baseline)
    proof=public_proof(work/'public.sqlite3',affected & rendered_ids(work/'public.sqlite3'))
    with readonly(master) as c:after={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in before}
    parsed=sum(len(r['rows']) for r in acquisition['results'])
    if sum(totals.values())!=parsed:raise ValueError('mansion_row_accounting_failed')
    return {'source':'mansion_review','integration_contract':'mansion-review-partial-v1','acquisition_status':'html_verified',
        'mansion_cycle':acquisition['cycle'],
        'parsed_rows':parsed,'attached_rows':totals['accepted_existing']+totals['accepted_new'],'row_counts':dict(totals),
        'html_count':len(acquisition['originals']),'pdf_count':0,'newly_acquired_pdf_count':0,
        'counts_before':before,'counts_after':after,'public_counts':counts,'proof':proof,'publication_area':area,
        'scope_results':scope_results,'historical_rows_preserved':True,'ulucks_preserved':True,'realpro_preserved':True,
        'successful_scopes':sum(r['status'] in ('success','confirmed_zero') for r in acquisition['results']),
        'absent_scopes':sum(r['status']=='no_source_page' for r in acquisition['results']),
        'failed_scopes':sum(r['status']=='failed' for r in acquisition['results'])}


def integrate(store,work,run,acquisition,source_commit,*,commit=False):
    # Caller already holds the shared collection lease. Backup is always made
    # against the current HEAD immediately before creating this candidate.
    head,generation,refs=backup(store,work,run)
    report=update(work/'master.sqlite3',acquisition,work,run,work/'baseline.sqlite3')
    report['backup_refs']=refs
    preserve_ulucks_catalog(store,head,run,report)
    report['original_manifest_ref']=save_json(store,work,f'private-runs/{run}/mansion-original-manifest.json',acquisition)
    report_ref=save_json(store,work,f'private-runs/{run}/mansion-report.json',report)
    if commit:
        # CAS never retries with a newer generation or rolls back another Job.
        if store.read_head()!=(head,generation):raise ValueError('mansion_head_changed_before_commit')
        head=commit_release(store,work,run,generation,report,source_commit)
    return {'status':'committed' if commit else 'validated_candidate','run_id':run,'head':head,'report_ref':report_ref,
        **{k:report[k] for k in ('counts_before','counts_after','row_counts','public_counts','successful_scopes','absent_scopes','failed_scopes')}}
