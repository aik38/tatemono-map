"""Provider-scoped RealPro ingestion using the existing registry and publisher."""
from __future__ import annotations

import json
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from tatemono_map.building_registry.ingest_master_import import ingest_master_import_csv, set_current_snapshot, _listing_key
from tatemono_map.cli.pdf_batch_run import RealproParser, write_master_import_csv, sha256_file, page_count_fast
from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.pipeline import validate_master, preservation_state, digest
from tatemono_map.cloud.public_db import export_public, rendered_ids
from tatemono_map.cloud.partial import literal_room, review_key
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.ulucks_geography import municipality_of


def scope_key(config):
    return 'realpro:' + digest({'company_id':config['company_id'],'area_id':'kitakyushu'})[:32]


def update(master, pdf, evidence, config, work, run, baseline):
    validate_master(master)
    parsed = RealproParser().parse(pdf)
    frame = parsed.df
    if len(frame) != evidence['expected_rows'] or frame.empty or not frame.category.eq('realpro').all():
        raise CollectionError('realpro_pdf_room_accounting_failed')
    if not frame.evidence_id.is_unique:
        raise CollectionError('realpro_evidence_ids_not_unique')
    if any(w != 'address_normalize_failed' for w in parsed.warnings):
        raise CollectionError('realpro_parser_context_failed')
    selected = {r['label'] for r in evidence['regions']}
    scope = scope_key(config)
    frame['evidence_id'] = frame.evidence_id.map(lambda v:f'cloud:{scope}:{run}:{v}')
    reasons = {}
    for row in frame.to_dict('records'):
        reason = None
        if municipality_of(row['address']) not in selected:
            reason = 'address_outside_selected_scope'
        elif not row['building_name'] or literal_room(row['room']) is None:
            reason = 'identity_unverified'
        elif not (row['rent_man'] > 0 and row['area_sqm'] > 0):
            reason = 'invalid_rent_or_area'
        if reason:
            reasons[row['evidence_id']] = reason
    if len(reasons) > max(2, len(frame)*0.20):
        raise CollectionError('realpro_excessive_invalid_rows')
    valid = frame.loc[~frame.evidence_id.isin(reasons)].copy()
    if valid.duplicated(['building_name','address','room']).any():
        raise CollectionError('realpro_duplicate_source_units')
    csv = work / 'realpro-import.csv'
    write_master_import_csv(valid, csv)
    with connect(master) as conn:
        tables = ('buildings','listings','sale_listings','raw_sources')
        before = {t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables}
        buildings = {r['building_id']:dict(r) for r in conn.execute('SELECT * FROM buildings')}
        preserved = preservation_state(conn)
        others = dict(conn.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots WHERE source<>?',(scope,)))
        previous = conn.execute('SELECT COUNT(*) FROM cloud_collection_rows WHERE ingest_run_id=(SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?)',(scope,)).fetchone()[0]
        if previous and len(frame) < previous*(1-float(config.get('max_drop_ratio',0.25))):
            raise CollectionError('realpro_scope_count_drop')
        old = conn.execute('''SELECT DISTINCT l.listing_key,l.building_key,l.room_label FROM listings l
            JOIN ingest_runs r ON r.id=l.ingest_run_id WHERE l.source_kind='realpro' AND
            ((r.source=? AND l.ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots))
             OR EXISTS(SELECT 1 FROM cloud_retained_listings h JOIN current_ingest_snapshots s
               ON h.scope_key=s.source AND h.ingest_run_id=s.ingest_run_id
               WHERE h.listing_key=l.listing_key AND h.scope_key=?))''',(scope,scope)).fetchall()
    report = ingest_master_import_csv(str(master),str(csv),source='realpro',snapshot_source=scope,
        snapshot_key=run,auto_seed_high_confidence=True)
    counts = Counter()
    with connect(master) as conn:
        # Lower-priority acquisition cannot overwrite the adopted registry's
        # existing attributes. Its offers still enter normal source selection.
        for key, original in buildings.items():
            current = conn.execute('SELECT * FROM buildings WHERE building_id=?',(key,)).fetchone()
            if current is None or current['canonical_name'] != original['canonical_name'] or current['canonical_address'] != original['canonical_address']:
                raise CollectionError('realpro_existing_canonical_changed')
            changed = [k for k in original if current[k] != original[k]]
            if changed:
                conn.execute('UPDATE buildings SET '+','.join('"'+k+'"=?' for k in changed)+' WHERE building_id=?',
                    (*[original[k] for k in changed],key))
        by_key = {r['listing_key']:dict(r) for r in conn.execute('SELECT * FROM listings WHERE ingest_run_id=?',(report.ingest_run_id,))}
        accepted = {}
        for row in valid.to_dict('records'):
            key = hashlib.sha256(f'{report.ingest_run_id}:{_listing_key(row)}'.encode()).hexdigest()
            if key in by_key:
                accepted[row['evidence_id']] = by_key[key]
        if len(accepted) != len(by_key):
            raise CollectionError('realpro_listing_evidence_mapping_failed')
        queued = {r['evidence_id']:dict(r) for r in conn.execute('SELECT * FROM unmatched_queue WHERE ingest_run_id=?',(report.ingest_run_id,))}
        fresh_units = {(r['building_key'],literal_room(r['room_label'])) for r in accepted.values()}
        if len(fresh_units) != len(accepted):
            raise CollectionError('realpro_duplicate_canonical_units')
        for row in frame.to_dict('records'):
            evidence_id = row['evidence_id']; listing = accepted.get(evidence_id)
            if listing:
                classification = 'accepted_existing' if listing['building_key'] in buildings else 'accepted_new'
                reason = ''
            else:
                classification = 'anomaly' if evidence_id in reasons else 'held'
                reason = reasons.get(evidence_id) or queued.get(evidence_id,{}).get('reason')
                if not reason:
                    raise CollectionError('realpro_unaccounted_parser_row')
            counts[classification] += 1
            conn.execute('INSERT INTO cloud_collection_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(
                scope,report.ingest_run_id,evidence_id,config['company_id'],
                review_key(scope,row['building_name'],row['address'],row['room']),classification,
                listing['building_key'] if listing else None,row['room'],json.dumps(row,ensure_ascii=False,default=str),
                reason,'[]',listing['listing_key'] if listing else None))
        # Unknown matches cannot authorize ending previous company offers.
        # Carry forward that company's unresolved units; other scopes are intact.
        retained = 0
        if counts['held'] or counts['anomaly']:
            for listing, building, room in old:
                if (building,literal_room(room)) not in fresh_units:
                    conn.execute('INSERT INTO cloud_retained_listings VALUES (?,?,?,?)',
                        (listing,scope,report.ingest_run_id,'realpro_pending_review'))
                    retained += 1
        aliases = dict(conn.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
        from tatemono_map.normalize.effective_rentals import canonical_key
        overlaps = 0
        # Scope ownership stays unchanged. Suppress only proven identical unit
        # identities from active RealPro history, never an Ulucks offer.
        for listing, building, room in conn.execute('''SELECT listing_key,building_key,room_label FROM listings
                WHERE source_kind='realpro' AND ingest_run_id<>? AND ingest_run_id IN
                (SELECT ingest_run_id FROM current_ingest_snapshots)''',(report.ingest_run_id,)):
            if (canonical_key(building,aliases),literal_room(room)) in fresh_units:
                conn.execute('INSERT INTO cloud_unit_overlaps VALUES (?,?,?)',(listing,scope,report.ingest_run_id));overlaps += 1
        set_current_snapshot(conn,scope,report.ingest_run_id)
        if dict(conn.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots WHERE source<>?',(scope,))) != others:
            raise CollectionError('realpro_other_snapshot_changed')
        if preservation_state(conn,preserved[0])[1] != preserved[1]:
            raise CollectionError('realpro_existing_history_changed')
        if conn.execute('PRAGMA foreign_key_check').fetchone():
            raise CollectionError('realpro_foreign_key_error')
    rebuild(str(master));validate_master(master)
    public_counts = export_public(master,work/'public.sqlite3',baseline=baseline)
    ids = rendered_ids(master)
    with connect(master) as conn:
        after = {t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in before}
        affected = ({r['building_key'] for r in accepted.values()} | {r[1] for r in old}) & ids
        proof = []
        for key in sorted(affected):
            summary = conn.execute('SELECT building_key,vacancy_count,rent_yen_min,rent_yen_max,area_sqm_min,area_sqm_max,layout_types_json FROM building_summaries WHERE building_key=?',(key,)).fetchone()
            if summary:
                value = dict(summary);value['layout_types']=json.loads(value.pop('layout_types_json') or '[]')
                fees = conn.execute('SELECT maint_yen_min,maint_yen_max FROM building_rental_summaries WHERE building_key=?',(key,)).fetchone()
                if fees:value.update(dict(fees))
                proof.append(value)
    if not proof:
        raise CollectionError('realpro_no_accepted_public_buildings')
    return dict(scope_key=scope,source='realpro',company_id=config['company_id'],area_id='kitakyushu',
        integration_contract='realpro-partial-v1',row_counts=dict(counts),parsed_rows=len(frame),
        parsed_buildings=len(frame[['building_name','address']].drop_duplicates()),attached_rows=len(accepted),
        matched_existing_rows=counts['accepted_existing'],new_buildings=after['buildings']-before['buildings'],
        held_rows=counts['held'],anomaly_rows=counts['anomaly'],retained_rows=retained,legacy_overlap_rows=overlaps,
        historical_rows_preserved=True,other_snapshots_preserved=True,counts_before=before,counts_after=after,
        pdf_count=1,pdf_pages=page_count_fast(pdf),pdfs=[{'pages':page_count_fast(pdf),'sha256':sha256_file(pdf)}],
        acquisition_status='pdf_verified',acquired_at=evidence['acquired_at'],processed_at=datetime.now(timezone.utc).isoformat(),
        public_counts=public_counts,proof=proof,ingest_run_id=report.ingest_run_id)
