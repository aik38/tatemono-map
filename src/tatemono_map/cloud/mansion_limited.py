"""Owner-directed rejudgment of explicit saved observations, without collecting.

Append newly validated offers to the original acquisition snapshot. Original
offers and decisions remain immutable; the rejudgment ledger links the new
import run, original scope/run/evidence and final listing key. This is an
extension of the same saved acquisition, not a replacement weekly snapshot.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tatemono_map.building_registry.ingest_master_import import MASTER_COLUMNS, _listing_key, ingest_master_import_csv
from tatemono_map.building_registry.keys import make_alias_key
from tatemono_map.building_registry.normalization import normalize_building_input, normalize_ulucks_name
from tatemono_map.cloud.mansion_integrate import master_row
from tatemono_map.cloud.pipeline import preservation_state, validate_master
from tatemono_map.cloud.public_db import export_public, readonly, rendered_ids, sha256, snapshot_sqlite, validate_public
from tatemono_map.cloud.realpro_batch import preserve_ulucks_catalog
from tatemono_map.cloud.realpro_weekly import save_json
from tatemono_map.cloud.mansion_weekly import wait_for_upstream
from tatemono_map.cloud.run import new_run_id
from tatemono_map.cloud.storage import GCSStore, commit_release
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.normalize.effective_rentals import canonical_key, effective_rentals, room_identity


def signature(row, bid):
    unit = room_identity(row['room'])
    return (bid, 'room', unit) if unit else (bid, 'anonymous', *terms(row))


def terms(row):
    return tuple(row[k] for k in ('floor', 'price_yen', 'area_sqm', 'layout', 'direction'))


def prepare(master, baseline, targets, work, run, *, baseline_master=None):
    validate_master(master)
    reference = baseline_master or master
    reference_hash = sha256(reference)
    receipt_path = work/'limited-import-receipt.json'
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    path = work/'limited-import.csv'
    saved_rows = None
    if receipt:
        if (not baseline_master or receipt['baseline_sha256'] != reference_hash
                or receipt['run_id'] != run or receipt['csv_sha256'] != sha256(path)):
            raise ValueError('invalid_rejudgment_import_checkpoint')
        with path.open(encoding='utf-8-sig',newline='') as f:
            saved_rows = list(csv.DictReader(f))
    with connect(reference) as c:
        original = {r['building_id']: dict(r) for r in c.execute('SELECT * FROM buildings')}
        old_aliases = {r['alias_key']: dict(r) for r in c.execute('SELECT * FROM building_key_aliases')}
        aliases = {k: r['canonical_key'] for k, r in old_aliases.items()}
        preserved = preservation_state(c)
        snapshots = dict(c.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots'))
        protected = {r['listing_key']: r for r in effective_rentals(c) if r['source_kind'] in ('ulucks', 'realpro')}
        bindings = {r[0]: (r[1], r[2]) for r in c.execute('SELECT * FROM mansion_review_building_bindings')}
        existing = defaultdict(list)
        for r in c.execute('''SELECT r.* FROM mansion_review_rows r JOIN mansion_review_scopes s
            ON s.scope_key=r.scope_key AND s.ingest_run_id=r.ingest_run_id
            WHERE r.classification LIKE 'accepted_%' '''):
            raw = json.loads(r['raw_json'])
            existing[(raw['kind'], signature(raw, canonical_key(r['building_id'], aliases)))].append(raw)
        seen = set()
        for t in targets:
            identity = (t['scope_key'], t['ingest_run_id'], t['evidence_id'])
            if identity in seen:
                raise ValueError('duplicate_rejudgment_target')
            seen.add(identity)
            old = c.execute('SELECT * FROM mansion_review_rows WHERE scope_key=? AND ingest_run_id=? AND evidence_id=?', identity).fetchone()
            if (not old or old['classification'] != 'held' or old['raw_json'] != t['raw_json']
                    or snapshots.get(t['scope_key']) != t['ingest_run_id']):
                raise ValueError('rejudgment_target_changed')
    now = saved_rows[0]['updated_at'] if saved_rows else datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M:%S')
    prepared = []
    lookup = {}
    for t in targets:
        raw = json.loads(t['raw_json'])
        if raw.get('reason') or not raw['source_url'] or not raw['building_url']:
            raise ValueError('invalid_rejudgment_row_context')
        if not (0 < raw['price_yen'] <= (10000000 if raw['kind'] == 'chintai' else 10000000000)
                and 5 <= raw['area_sqm'] <= 2000):
            raise ValueError('invalid_rejudgment_numeric_terms')
        evidence = t['evidence_id'] + '#limited=' + run
        pr = master_row(raw, evidence, now)
        prepared.append(pr)
        lookup[evidence] = (t, raw, pr)
    temporary_scope = 'mansion_review:limited:' + run
    if receipt:
        if saved_rows != prepared:
            raise ValueError('rejudgment_checkpoint_rows_changed')
        rid = receipt['ingest_run_id']
        with connect(master) as c:
            found = c.execute('SELECT source,snapshot_key,status FROM ingest_runs WHERE id=?',(rid,)).fetchone()
            active = c.execute('SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?',(temporary_scope,)).fetchone()
            if tuple(found or ()) != (temporary_scope,sha256(path),'completed') or (active and active[0] != rid):
                raise ValueError('rejudgment_checkpoint_run_changed')
    else:
        with path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=MASTER_COLUMNS)
            writer.writeheader()
            writer.writerows(prepared)
        imported = ingest_master_import_csv(str(master), str(path), source='mansion_review',
            snapshot_source=temporary_scope, snapshot_key=sha256(path),
            auto_seed_high_confidence=True, strict_name_match=True, exact_name_match=True)
        rid = imported.ingest_run_id
        receipt_path.write_text(json.dumps(dict(run_id=run,ingest_run_id=rid,
            csv_sha256=sha256(path),baseline_sha256=reference_hash)))
    with connect(master) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS mansion_review_rejudgments (
            operation TEXT,scope_key TEXT,original_ingest_run_id INTEGER,original_evidence_id TEXT,
            import_run_id INTEGER,cause TEXT,classification TEXT,reason TEXT,building_id TEXT,listing_key TEXT,
            PRIMARY KEY(operation,scope_key,original_ingest_run_id,original_evidence_id))''')
        aliases = dict(c.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
        accepted = {}
        reasons = {}
        for e, (t, raw, pr) in lookup.items():
            table, keycol = ('listings', 'listing_key') if raw['kind'] == 'chintai' else ('sale_listings', 'sale_listing_key')
            key = hashlib.sha256(f"{rid}:{_listing_key(pr)}".encode()).hexdigest()
            offer = c.execute(f'SELECT * FROM {table} WHERE {keycol}=? AND ingest_run_id=?', (key, rid)).fetchone()
            if not offer:
                q = c.execute('SELECT reason FROM unmatched_queue WHERE ingest_run_id=? AND evidence_id=?', (rid, e)).fetchone()
                reasons[e] = q[0] if q else 'unresolved_canonical_match'
                continue
            bid = canonical_key(offer['building_key'], aliases)
            n = normalize_building_input(raw['building_name'], raw['address'])
            binding = bindings.get(raw['building_url'])
            if binding and (canonical_key(binding[0], aliases) != bid or binding[1] != n.normalized_address):
                reasons[e] = 'provider_building_identity_conflict'
            else:
                accepted[e] = (bid, key, table, keycol)
        urls = defaultdict(set)
        groups = defaultdict(list)
        for e, (bid, *_) in accepted.items():
            raw = lookup[e][1]
            urls[raw['building_url']].add(bid)
            groups[(raw['kind'], signature(raw, bid))].append(e)
        for e in list(accepted):
            if len(urls[lookup[e][1]['building_url']]) != 1:
                reasons[e] = 'provider_building_identity_conflict'
        for (kind, identity), group in groups.items():
            raw_terms = {terms(lookup[e][1]) for e in group}
            prior = existing.get((kind, identity), [])
            if len(raw_terms) > 1 or (prior and any(terms(p) not in raw_terms for p in prior)):
                for e in group:
                    reasons[e] = 'conflicting_unit_terms'
            elif prior:
                for e in group:
                    reasons[e] = 'duplicate_advertisement'
            else:
                for e in group[1:]:
                    reasons[e] = 'duplicate_advertisement'
        for e in reasons:
            accepted.pop(e, None)
        approved_aliases = set()
        for e, (bid, key, table, keycol) in accepted.items():
            t, raw, _ = lookup[e]
            n = normalize_building_input(raw['building_name'], raw['address'])
            approved_aliases.add(make_alias_key(n.normalized_name, n.normalized_address))
            approved_aliases.add(bid)
            # This saved observation belongs to the existing active scope.
            # Keep its original active run and record the operator import run
            # separately; do not expire or replace any accepted snapshot.
            c.execute(f'UPDATE {table} SET ingest_run_id=?,source_url=? WHERE {keycol}=? AND ingest_run_id=?',
                (t['ingest_run_id'], raw['source_url'], key, rid))
            c.execute('INSERT OR IGNORE INTO mansion_review_building_bindings VALUES (?,?,?)',
                (raw['building_url'], bid, n.normalized_address))
            if raw['kind'] == 'mansion':
                c.execute('INSERT OR IGNORE INTO mansion_review_sale_buildings VALUES (?,?)', (bid, t['scope_key']))
        # Only newly created, rejected trial offers and associations are removed.
        # All original histories are checked byte-for-byte below.
        for table in ('listings', 'sale_listings'):
            c.execute(f'DELETE FROM {table} WHERE ingest_run_id=?', (rid,))
        rejected = set(lookup) - set(accepted)
        for e in rejected:
            c.execute('DELETE FROM building_sources WHERE rowid>? AND evidence_id=?', (preserved[0]['building_sources'], e))
        for r in c.execute('SELECT alias_key FROM building_key_aliases').fetchall():
            if r[0] not in old_aliases and r[0] not in approved_aliases:
                c.execute('DELETE FROM building_key_aliases WHERE alias_key=?', (r[0],))
        c.execute('DELETE FROM current_ingest_snapshots WHERE source=? AND ingest_run_id=?', (temporary_scope, rid))
        for bid, old in original.items():
            current = c.execute('SELECT * FROM buildings WHERE building_id=?', (bid,)).fetchone()
            if not current:
                raise ValueError('existing_canonical_removed')
            changed = [k for k in old if current[k] != old[k]]
            if changed:
                c.execute('UPDATE buildings SET '+','.join('"'+k+'"=?' for k in changed)+' WHERE building_id=?',
                    (*[old[k] for k in changed], bid))
        for key, old in old_aliases.items():
            current = c.execute('SELECT * FROM building_key_aliases WHERE alias_key=?', (key,)).fetchone()
            if not current or current['canonical_key'] != old['canonical_key']:
                raise ValueError('existing_alias_retargeted')
            if dict(current) != old:
                c.execute('UPDATE building_key_aliases SET updated_at=? WHERE alias_key=?', (old['updated_at'], key))
        counts = Counter()
        details = []
        for e, (t, raw, _) in lookup.items():
            offer = accepted.get(e)
            cls = ('accepted_existing' if offer[0] in original else 'accepted_new') if offer else 'held'
            counts[cls] += 1
            reason = reasons.get(e, '')
            c.execute('INSERT INTO mansion_review_rejudgments VALUES (?,?,?,?,?,?,?,?,?,?)',
                (run,t['scope_key'],t['ingest_run_id'],t['evidence_id'],rid,t['cause'],cls,reason,
                 offer[0] if offer else None,offer[1] if offer else None))
            details.append(dict(cause=t['cause'],classification=cls,reason=reason,
                evidence_id=t['evidence_id'],building_id=offer[0] if offer else None,
                source_url=raw['source_url'],building_url=raw['building_url'],
                name=raw['building_name'],address=raw['address']))
        new_ids = {r[0] for r in c.execute('SELECT building_id FROM buildings')} - set(original)
        adopted_new = {o[0] for o in accepted.values()} - set(original)
        if new_ids != adopted_new:
            raise ValueError('new_unadopted_canonical_asset')
        original_pairs = {(normalize_ulucks_name(b['canonical_name']).replace(' ', ''),
            normalize_building_input(b['canonical_name'], b['canonical_address']).normalized_address) for b in original.values()}
        new_pairs = set()
        for bid in new_ids:
            b = c.execute('SELECT canonical_name,canonical_address FROM buildings WHERE building_id=?', (bid,)).fetchone()
            n = normalize_building_input(*b)
            pair = (normalize_ulucks_name(b[0]).replace(' ', ''), n.normalized_address)
            if pair in original_pairs or pair in new_pairs:
                raise ValueError('new_duplicate_canonical_asset')
            new_pairs.add(pair)
        if preservation_state(c, preserved[0])[1] != preserved[1]:
            raise ValueError('existing_history_changed')
        if dict(c.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots')) != snapshots:
            raise ValueError('existing_snapshot_changed')
        protected_after = {r['listing_key']: r for r in effective_rentals(c) if r['source_kind'] in ('ulucks', 'realpro')}
        if protected_after != protected:
            raise ValueError('ulucks_realpro_effective_rows_changed')
    rebuild(str(master))
    validate_master(master)
    public_counts = export_public(master, work/'public.sqlite3', baseline=baseline)
    if not rendered_ids(baseline) <= rendered_ids(work/'public.sqlite3'):
        raise ValueError('existing_public_building_missing')
    with readonly(baseline) as old, readonly(work/'public.sqlite3') as new:
        previous_sales = dict(old.execute('SELECT building_key,COALESCE(sale_listing_count,0) FROM building_summaries'))
        current_sales = dict(new.execute('SELECT building_key,COALESCE(sale_listing_count,0) FROM building_summaries'))
        if any(current_sales.get(bid, 0) < n for bid, n in previous_sales.items()):
            raise ValueError('existing_sale_offers_missing')
    return dict(target_rows=len(targets),row_counts=dict(counts),new_buildings=len(new_ids),
        existing_buildings=len({o[0] for o in accepted.values() if o[0] in original}),
        public_counts=public_counts,details=details,historical_rows_preserved=True,
        ulucks_preserved=True,realpro_preserved=True,snapshots_preserved=True,
        new_duplicate_buildings=0,new_html_requests=0,new_pdf_requests=0)


def publish(store, manifest, work, source_commit):
    head, generation = store.read_head()
    if generation != manifest['expected_generation'] or head['run_id'] != manifest['baseline_run']:
        raise ValueError('rejudgment_head_changed')
    if source_commit != manifest['source_commit']:
        raise ValueError('rejudgment_source_commit_changed')
    with store.collection_lease('mansion-limited:'+manifest['run_id']):
        store.download(manifest['master'],work/'master.sqlite3')
        store.download(manifest['public'],work/'public.sqlite3')
        validate_master(work/'master.sqlite3')
        validate_public(work/'public.sqlite3')
        # Independently compare the packaged candidate to its exact baseline.
        store.download(head['master'],work/'baseline-master.sqlite3')
        with readonly(work/'baseline-master.sqlite3') as old, readonly(work/'master.sqlite3') as new:
            old.row_factory = new.row_factory = sqlite3.Row
            preserved = preservation_state(old)
            if preservation_state(new,preserved[0])[1] != preserved[1]:
                raise ValueError('candidate_history_changed')
            for row in old.execute('SELECT * FROM buildings'):
                current = new.execute('SELECT * FROM buildings WHERE building_id=?',(row['building_id'],)).fetchone()
                if not current or tuple(current) != tuple(row):
                    raise ValueError('candidate_existing_building_changed')
            for table in ('current_ingest_snapshots','mansion_review_scopes'):
                if [tuple(r) for r in old.execute('SELECT * FROM '+table+' ORDER BY 1')] != [tuple(r) for r in new.execute('SELECT * FROM '+table+' ORDER BY 1')]:
                    raise ValueError('candidate_snapshots_changed')
            protected = lambda c: {r['listing_key']:r for r in effective_rentals(c) if r['source_kind'] in ('ulucks','realpro')}
            if protected(old) != protected(new):
                raise ValueError('candidate_upstream_changed')
        report = manifest['report']
        from tatemono_map.cloud.fetch_public import validate_collection_proof
        validate_collection_proof(report)
        if validate_public(work/'public.sqlite3') != report['public_counts']:
            raise ValueError('candidate_public_counts_changed')
        preserve_ulucks_catalog(store,head,manifest['run_id'],report)
        if store.read_head() != (head,generation):
            raise ValueError('rejudgment_head_changed_before_commit')
        result = commit_release(store,work,manifest['run_id'],generation,report,source_commit)
        save_json(store,work,'private-runs/'+manifest['run_id']+'/limited-result.json',result)
        return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest',required=True)
    args = p.parse_args()
    store = GCSStore(os.environ['TATEMONO_BUCKET'])
    wait_for_upstream(os.environ['GOOGLE_CLOUD_PROJECT'],os.environ.get('TATEMONO_REGION','asia-northeast1'),weekly=False)
    import tempfile
    with tempfile.TemporaryDirectory(prefix='mr-limited-') as directory:
        work=Path(directory)
        blob=store.bucket.blob(args.manifest)
        blob.reload()
        manifest=json.loads(blob.download_as_bytes(if_generation_match=int(blob.generation)))
        result=publish(store,manifest,work,os.environ['TATEMONO_SOURCE_COMMIT'])
        print('MANSION_LIMITED_COMMITTED='+json.dumps(dict(run_id=result['run_id'],public_counts=result['report']['public_counts'])),flush=True)


if __name__ == '__main__':
    main()
