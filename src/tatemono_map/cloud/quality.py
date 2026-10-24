"""Evidence-based maintenance of the adopted master; no acquisition or source switch."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from tatemono_map.building_registry.merge import name_identity, full_address, merge_confirmed
from tatemono_map.building_registry.normalization import normalize_address_for_matching
from tatemono_map.normalize.effective_rentals import effective_rentals, canonical_key, room_identity
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.cloud.public_db import export_public, rendered_ids, readonly
from tatemono_map.cloud.storage import collection_run_id, commit_release, validate_head
from tatemono_map.cloud.pipeline import validate_master
from tatemono_map.cloud.batch import public_proof
from tatemono_map.cloud.run import new_run_id


def plan(conn):
    bs={r['building_id']:dict(r) for r in conn.execute('SELECT * FROM buildings')}
    groups=defaultdict(list)
    evidence=defaultdict(set)
    for b in bs.values():groups[name_identity(b['canonical_name'])].append(b)
    for source in conn.execute('SELECT building_id,raw_name,raw_address FROM building_sources'):
        key,name,address=source
        if key in bs and name_identity(name)==name_identity(bs[key]['canonical_name']) and full_address(address):
            evidence[key].add(normalize_address_for_matching(address))
    aliases=dict(conn.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
    merges=[];pending=[];distinct=[];pairs=[]
    for name,group in groups.items():
        if not name or len(group)<2:continue
        # Deterministic disjoint evidence components; no incomplete-address transitive union.
        by_addr=defaultdict(list)
        for b in group:
            address=normalize_address_for_matching(b['canonical_address'])
            if full_address(b['canonical_address']):by_addr[address].append(b)
        used=set()
        for address,full in by_addr.items():
            confirmed=list(full)
            for b in group:
                if b in full:continue
                # A source record attached to this very ID must state the same full lot.
                if address in evidence[b['building_id']]:confirmed.append(b)
            confirmed=[b for b in confirmed if b['building_id'] not in used]
            if len(confirmed)<2:continue
            built={b['built_year_month'] for b in confirmed if b['built_year_month']}
            if len(built)>1:
                pending.append({'ids':[b['building_id'] for b in confirmed],'reason':'conflicting_built_dates'});continue
            roots={canonical_key(b['building_id'],aliases) for b in confirmed}
            confirmed_ids={b['building_id'] for b in confirmed}
            if not roots <= confirmed_ids:
                pending.append({'ids':sorted(confirmed_ids),'reason':'existing_alias_conflict'});continue
            # Preserve an established canonical endpoint and published full identity.
            confirmed.sort(key=lambda b:(canonical_key(b['building_id'],aliases)!=b['building_id'],b['hidden_from_public']!=0,not full_address(b['canonical_address']),b['created_at'] or '9999',b['building_id']))
            keep=confirmed[0]
            for drop in confirmed[1:]:
                merges.append({'keep':keep['building_id'],'drop':drop['building_id'],'name':keep['canonical_name'],'reason':'same_name_full_lot_with_source_evidence'})
            used.update(b['building_id'] for b in confirmed)
        for i,a in enumerate(group):
            for b in group[i+1:]:
                aa=normalize_address_for_matching(a['canonical_address']);bb=normalize_address_for_matching(b['canonical_address'])
                ids=[a['building_id'],b['building_id']]
                if aa==bb or (aa and bb and (aa.startswith(bb+'-') or bb.startswith(aa+'-'))):
                    pairs.append(ids)
                    if not all(x in used for x in ids):pending.append({'ids':ids,'reason':'incomplete_or_unverified_lot'})
                else:distinct.append(ids)
    # Canonical full-lot pairs may be merged despite unrelated ambiguous candidates.
    return {'merges':merges,'pending':pending,'distinct':distinct,'candidate_pairs':pairs}


def maintain(master, apply=True, target_ids=None):
    conn=sqlite3.connect(master);conn.row_factory=sqlite3.Row
    before={t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('buildings','listings','sale_listings','building_sources','raw_sources')}
    source_counts=dict(conn.execute('SELECT source_kind,COUNT(*) FROM listings GROUP BY source_kind'))
    snapshot_before=[tuple(r) for r in conn.execute('SELECT * FROM current_ingest_snapshots ORDER BY source')]
    priorities_before=[tuple(r) for r in conn.execute('SELECT * FROM source_priority ORDER BY source')]
    proposal=plan(conn)
    if not apply:return proposal
    # Persist row-specific decisions. History, source rows, snapshot pointers and
    # numeric terms are retained; only publication eligibility changes.
    conn.execute('CREATE TABLE IF NOT EXISTS quality_listing_holds (listing_key TEXT PRIMARY KEY,reason TEXT NOT NULL,original_building_key TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,resolved_at TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS quality_building_holds (building_id TEXT PRIMARY KEY,reason TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    conn.execute('CREATE TABLE IF NOT EXISTS quality_blocked_building_aliases (alias_key TEXT PRIMARY KEY,reason TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    originals={r['listing_key']:dict(r) for r in conn.execute('SELECT * FROM listings')}
    missing=[r for r in originals.values() if r['ingest_run_id']==31 and r['source_kind']=='mansion_review_chintai' and r['rent_yen'] is None and r['area_sqm'] is None]
    targets=[r for r in missing if target_ids is None or r['building_key'] in target_ids]
    from tatemono_map.cloud.legacy_rent_evidence import locate,shifted_terms
    found,evidence_diagnostics=locate(conn,targets)
    restorations={key:shifted_terms(raw) for key,raw in found.items() if shifted_terms(raw)}
    conn.execute('CREATE TABLE IF NOT EXISTS quality_rental_repairs (listing_key TEXT PRIMARY KEY,reason TEXT NOT NULL,original_row_json TEXT NOT NULL,source_sha256 TEXT NOT NULL,repaired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    for row in missing:
        conn.execute('INSERT OR IGNORE INTO quality_listing_holds(listing_key,reason,original_building_key) VALUES (?,?,?)',(row['listing_key'],'legacy_import_missing_terms_and_unit_no_current_verification',row['building_key']))
    for key,terms in restorations.items():
        conn.execute('INSERT OR IGNORE INTO quality_rental_repairs(listing_key,reason,original_row_json,source_sha256) VALUES (?,?,?,?)',(key,'audited_legacy_header_cell_offset',json.dumps(originals[key],ensure_ascii=False),hashlib.sha256(found[key].encode()).hexdigest()))
        conn.execute('UPDATE listings SET rent_yen=?,area_sqm=? WHERE listing_key=?',(terms['rent_yen'],terms['area_sqm'],key))
    with conn:
        for m in proposal['merges']:merge_confirmed(conn,m['keep'],m['drop'],m['reason'])
    # Suspected duplicate partial identities stay private pending positive lot proof.
    merged_ids={m['drop'] for m in proposal['merges']}
    hold_buildings=set()
    for pending in proposal['pending']:
        for key in pending['ids']:
            if key in merged_ids:continue
            row=conn.execute('SELECT canonical_address FROM buildings WHERE building_id=?',(key,)).fetchone()
            addresses=[r[0] for other in pending['ids'] if other!=key for r in conn.execute('SELECT canonical_address FROM buildings WHERE building_id=?',(other,))]
            address=normalize_address_for_matching(row[0]) if row else ''
            shorter=any(normalize_address_for_matching(a).startswith(address+'-') for a in addresses) if address else False
            if row and (not full_address(row[0]) or shorter or pending['reason']=='conflicting_built_dates'):
                hold_buildings.add(key)
                conn.execute('UPDATE buildings SET hidden_from_public=1 WHERE building_id=?',(key,))
                conn.execute('INSERT OR IGNORE INTO quality_building_holds(building_id,reason) VALUES (?,?)',(key,pending['reason']))
    # On repaired buildings a recent managed snapshot is positive evidence for
    # its observed units; a pre-cloud legacy offer is not proof of another current vacancy.
    touched={m['keep'] for m in proposal['merges']}
    superseded=[]
    runs=dict(conn.execute('SELECT id,source FROM ingest_runs'))
    active=set(r[0] for r in conn.execute('SELECT ingest_run_id FROM current_ingest_snapshots'))
    all_current=[dict(r) for r in conn.execute('SELECT * FROM listings') if r['ingest_run_id'] in active]
    managed=defaultdict(set)
    for row in all_current:
        if row['building_key'] in touched and ':' in runs.get(row['ingest_run_id'],''):
            managed[(row['building_key'],row['source_kind'])].add(room_identity(row['room_label']))
    for row in all_current:
        scope=(row['building_key'],row['source_kind'])
        if (row['building_key'] in touched and row['ingest_run_id'] in (4,7,31)
                and ':' not in runs.get(row['ingest_run_id'],'')
                and room_identity(row['room_label']) not in managed.get(scope,set())):
            superseded.append(row['listing_key'])
            conn.execute('INSERT OR IGNORE INTO quality_listing_holds(listing_key,reason,original_building_key) VALUES (?,?,?)',(row['listing_key'],'legacy_offer_not_confirmed_by_current_managed_snapshot',originals[row['listing_key']]['building_key']))
    # Name/lot disagreement in a currently selected offer cannot be repaired by
    # merging the building. Record it separately; never borrow another unit's price.
    bindings={r['building_id']:dict(r) for r in conn.execute('SELECT * FROM buildings')}
    wrong=[]
    for row in effective_rentals(conn):
        b=bindings.get(row['building_key'])
        if not b:raise ValueError('quality_orphan_effective_listing')
        if (name_identity(row['name']) != name_identity(b['canonical_name'])
                and (not full_address(row['address']) or normalize_address_for_matching(row['address']) != normalize_address_for_matching(b['canonical_address']))):
            from difflib import SequenceMatcher
            if SequenceMatcher(None,name_identity(row['name']),name_identity(b['canonical_name'])).ratio()<0.65:
                wrong.append(row['listing_key'])
                from tatemono_map.building_registry.keys import make_alias_key,make_legacy_alias_key
                from tatemono_map.building_registry.normalization import normalize_building_input,normalize_ulucks_name
                normalized=normalize_building_input(row['name'],row['address'])
                names={normalized.normalized_name,normalize_ulucks_name(row['name'])}
                for name in names:
                    for key_fn in (make_alias_key,make_legacy_alias_key):
                        key=key_fn(name,normalized.normalized_address)
                        conn.execute('INSERT OR IGNORE INTO quality_blocked_building_aliases(alias_key,reason) VALUES (?,?)',(key,'unverified_legacy_identity_binding'))
                conn.execute('INSERT OR IGNORE INTO quality_listing_holds(listing_key,reason,original_building_key) VALUES (?,?,?)',(row['listing_key'],'rental_name_contradicts_canonical_identity',originals[row['listing_key']]['building_key']))
    conn.commit()
    after={t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in before}
    if after['buildings'] != before['buildings']-len(proposal['merges']):raise ValueError('quality_unplanned_building_loss')
    if snapshot_before != [tuple(r) for r in conn.execute('SELECT * FROM current_ingest_snapshots ORDER BY source')]:raise ValueError('quality_snapshot_changed')
    if priorities_before != [tuple(r) for r in conn.execute('SELECT * FROM source_priority ORDER BY source')]:raise ValueError('quality_priority_changed')
    if any(after[t]!=before[t] for t in before if t!='buildings'):raise ValueError('quality_history_count_changed')
    if dict(conn.execute('SELECT source_kind,COUNT(*) FROM listings GROUP BY source_kind'))!=source_counts:raise ValueError('quality_source_count_changed')
    # Every old listing's non-binding fields must be byte-for-byte identical.
    changed=[]
    for r in conn.execute('SELECT * FROM listings'):
        row=dict(r);old=originals[row['listing_key']]
        allowed={'building_key'} | (set(restorations[row['listing_key']]) if row['listing_key'] in restorations else set())
        if any(row[k]!=v for k,v in old.items() if k not in allowed):raise ValueError('quality_rental_terms_changed_without_evidence')
        if row['building_key']!=old['building_key']:changed.append(row['listing_key'])
    conn.close();rebuild(str(master));validate_master(Path(master))
    with readonly(Path(master)) as c:
        # No alias cycle or public summary referencing a removed canonical row.
        ids={r[0] for r in c.execute('SELECT building_id FROM buildings')}
        aliases=dict(c.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
        for alias in aliases:canonical_key(alias,aliases)
        if any(r[0] not in ids for r in c.execute('SELECT building_key FROM building_summaries')):raise ValueError('quality_orphan_summary')
    return {**proposal,'counts_before':before,'counts_after':after,'history_terms_preserved_except_audited_repairs':True,'target_missing_rows':len(targets),'target_missing_buildings':len({r['building_key'] for r in targets}),'rent_area_restored':len(restorations),'original_row_unresolved':len(targets)-len(restorations),'source_counts':source_counts,'legacy_missing_rows':len(missing),'legacy_missing_buildings':len({r['building_key'] for r in missing}),'held_buildings':sorted(hold_buildings),'identity_mismatch_holds':len(wrong),'legacy_unconfirmed_holds':len(superseded),'rebound_history_rows':len(changed)}


def release(store, work, source_commit, expected_generation, *, commit=False):
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    with store.collection_lease('quality-'+source_commit):
        head,generation=store.read_head();validate_head(head)
        if generation!=expected_generation:raise ValueError('quality_head_generation_changed_replan_required')
        store.download(head['master'],work/'master.sqlite3');store.download(head['public'],work/'baseline.sqlite3')
        validate_master(work/'master.sqlite3')
        run=new_run_id()
        # Immutable pre-change backup and inherited pointer precede every modification.
        backup=store.upload(work/'master.sqlite3',f'backups/{run}.sqlite3')
        p=work/'inherited-head.json';p.write_text(json.dumps(head,sort_keys=True))
        inherited=store.upload(p,f'private-runs/{run}/inherited-head.json')
        with readonly(work/'baseline.sqlite3') as baseline:
            target_ids={r[0] for r in baseline.execute('SELECT building_key FROM building_summaries WHERE vacancy_count>0 AND rent_yen_min IS NULL AND area_sqm_min IS NULL')}
        result=maintain(work/'master.sqlite3',target_ids=target_ids)
        counts=export_public(work/'master.sqlite3',work/'public.sqlite3',baseline=work/'baseline.sqlite3')
        result.update(backup=backup,before_public_counts=head['report']['public_counts'],public_counts=counts,expected_generation=generation)
        p=work/'quality-report.json';p.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True))
        report_ref=store.upload(p,f'private-runs/{run}/quality-report.json')
        if not commit:return {'dry_run':True,'report_ref':report_ref,**result}
        report=copy.deepcopy(head['report'])
        report.update(release_kind='publication_only',collection_run_id=collection_run_id(head),inherited_head_ref=inherited,inherited_head_generation=generation,newly_acquired_pdf_count=0,public_counts=counts,proof=public_proof(work/'public.sqlite3',rendered_ids(work/'public.sqlite3')),quality_maintenance_ref=report_ref)
        if store.read_head()!=(head,generation):raise ValueError('quality_head_changed')
        new=commit_release(store,work,run,generation,report,source_commit)
        return {'dry_run':False,'release':new['run_id'],'generation':store.read_head()[1],'report_ref':report_ref,**result}
