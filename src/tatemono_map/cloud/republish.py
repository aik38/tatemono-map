"""Publish an adopted master without logging in, collecting, or changing it."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sqlite3
from pathlib import Path

from tatemono_map.cloud.batch import public_proof
from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.fetch_public import accounted_collection, validate_collection_proof
from tatemono_map.cloud.pipeline import validate_master
from tatemono_map.cloud.public_db import export_public, publication_ids, readonly, rendered_ids, sha256, validate_public
from tatemono_map.cloud.storage import GCSStore, collection_run_id, commit_release, validate_head


def validate_collection_references(store, head, master, work):
    """Verify inherited evidence and the actual current company snapshots."""
    report = head['report']
    validate_collection_proof(report)
    catalog = report.get('company_catalog_ref')
    if catalog:
        if catalog['object'] != f'private-runs/{collection_run_id(head)}/company-catalog.json':
            raise CollectionError('previous_company_catalog_reference_invalid')
        store.download(catalog, work / 'inherited-catalog.json')
    entries = report.get('company_results', [])
    if report.get('collection_mode') == 'all_companies' and len(entries) != report['successful_companies']:
        raise CollectionError('inherited_company_results_missing')
    with readonly(master) as conn:
        for entry in entries:
            path = work / 'inherited-company.json'
            store.download(entry['result_ref'], path)
            result = json.loads(path.read_text())
            if not accounted_collection(result):
                raise CollectionError('inherited_company_accounting_invalid')
            current = conn.execute('SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?',
                (result['scope_key'],)).fetchone()
            count = conn.execute('SELECT COUNT(*) FROM listings WHERE ingest_run_id=?',
                (result['ingest_run_id'],)).fetchone()[0]
            if (not current or current[0] != result['ingest_run_id'] or
                    count != result['attached_rows'] or result['company_id'] != entry['company_id']):
                raise CollectionError('inherited_company_snapshot_mismatch')
            manifest = result.get('acquisition_manifest_ref')
            if manifest is None:
                raise CollectionError('inherited_acquisition_manifest_missing')
            store.download(manifest, work / 'inherited-manifest.json')


def republish(store, work: Path, source_commit: str, expected_generation: int, *, quarantine_ids=()) -> dict:
    from tatemono_map.cloud.run import new_run_id
    head, generation = store.read_head()
    validate_head(head)
    if generation != expected_generation:
        raise CollectionError('previous_head_changed')
    work.mkdir(parents=True, exist_ok=True)
    for key, filename in [('master', 'master.sqlite3'), ('public', 'publication-baseline.sqlite3')]:
        path = work / filename
        if not path.is_file() or sha256(path) != head[key]['sha256']:
            store.download(head[key], path)
    master = work / 'master.sqlite3'
    validate_master(master)
    if validate_public(work / 'publication-baseline.sqlite3') != head['report']['public_counts']:
        raise CollectionError('publication_baseline_counts_mismatch')
    validate_collection_references(store, head, master, work)
    # One-time migration of an already persisted provisional seed. This is an
    # explicit use of the existing hidden flag, never a publication allowlist.
    # Only never-published rows with no adopted rental/sale offer and positive
    # private held-row evidence qualify. Preserve their IDs and every history.
    previous_ids, _ = publication_ids(work / 'publication-baseline.sqlite3')
    with sqlite3.connect(master) as conn:
        for key in quarantine_ids:
            if (key in previous_ids or
                    not conn.execute('SELECT 1 FROM buildings WHERE building_id=?', (key,)).fetchone() or
                    conn.execute('SELECT 1 FROM listings WHERE building_key=?', (key,)).fetchone() or
                    conn.execute('SELECT 1 FROM sale_listings WHERE building_key=?', (key,)).fetchone() or
                    not conn.execute("SELECT 1 FROM cloud_collection_rows WHERE building_id=? AND classification IN ('held','anomaly')", (key,)).fetchone() or
                    conn.execute("SELECT 1 FROM cloud_collection_rows WHERE building_id=? AND classification NOT IN ('held','anomaly')", (key,)).fetchone()):
                raise CollectionError('migration_quarantine_not_proven')
            conn.execute('UPDATE buildings SET hidden_from_public=1 WHERE building_id=?', (key,))
    counts = export_public(master, work / 'public.sqlite3', baseline=work / 'publication-baseline.sqlite3')
    ids, _ = publication_ids(master)
    with readonly(work / 'public.sqlite3') as conn:
        if {r[0] for r in conn.execute('SELECT building_id FROM buildings')} != ids:
            raise CollectionError('publication_id_set_mismatch')
    run = new_run_id()
    previous = work / 'inherited-head.private.json'
    previous.write_text(json.dumps(head, sort_keys=True))
    inherited = store.upload(previous, f'private-runs/{run}/inherited-head.json')
    # Acquisition fields describe the inherited collection, never this publish.
    report = copy.deepcopy(head['report'])
    report.update(release_kind='publication_only', collection_run_id=collection_run_id(head),
        inherited_head_ref=inherited, inherited_head_generation=generation,
        newly_acquired_pdf_count=0, public_counts=counts,
        proof=public_proof(work / 'public.sqlite3', rendered_ids(work / 'public.sqlite3')))
    if quarantine_ids:
        audit = work / 'migration-exclusions.private.json'
        audit.write_text(json.dumps({'reason': 'persisted_provisional_seed_with_only_held_rows',
            'building_ids': sorted(quarantine_ids), 'before_master': head['master']}))
        report['migration_exclusions_ref'] = store.upload(audit, f'private-runs/{run}/migration-exclusions.json')
    if store.read_head() != (head, generation):
        raise CollectionError('previous_head_changed')
    return commit_release(store, work, run, generation, report, source_commit,
        master_reference=head['master'] if not quarantine_ids else None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--expected-generation', type=int, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--quarantine-unadopted-building', action='append', default=[])
    args = parser.parse_args()
    os.umask(0o077)
    store = GCSStore(args.bucket)
    with store.collection_lease('publication-only-' + args.source_commit):
        head = republish(store, args.work, args.source_commit, args.expected_generation,
            quarantine_ids=args.quarantine_unadopted_building)
    print(json.dumps({'release': head['run_id'], 'public_counts': head['report']['public_counts'],
        'master_sha256': head['master']['sha256'], 'newly_acquired_pdf_count': 0}))


if __name__ == '__main__':
    main()
