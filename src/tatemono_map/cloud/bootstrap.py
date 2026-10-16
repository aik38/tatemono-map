"""Durable registration of one verified private master, never an inferred DB."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.public_db import export_public, sha256, snapshot_sqlite
from tatemono_map.cloud.storage import RUN_RE, TRANSFER_TIMEOUT, UPLOAD_CHUNK_BYTES, validate_head


def save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def prepare(master, expected_sha256, work, source_commit, *, candidates=(), recover=False, previous_commits=(), bucket=None):
    from tatemono_map.cloud.pipeline import validate_master
    from tatemono_map.cloud.run import new_run_id
    if any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{40}', value) for value in (source_commit, *previous_commits)):
        raise CollectionError('bootstrap_source_commit_invalid')
    if sha256(master) != expected_sha256:
        raise CollectionError('bootstrap_master_checksum_required')
    validate_master(master)
    if Path(str(master) + '-wal').exists():
        raise CollectionError('bootstrap_requires_closed_checkpointed_master')
    work.mkdir(parents=True, exist_ok=True)
    work.chmod(0o700)
    snapshot_sqlite(master, work / 'master.sqlite3')
    counts = export_public(work / 'master.sqlite3', work / 'public.sqlite3')
    binding = {'input_master_sha256': expected_sha256, 'master_sha256': sha256(work / 'master.sqlite3'), 'public_sha256': sha256(work / 'public.sqlite3'), 'bucket': bucket}
    path = work / 'bootstrap-progress.private.json'
    if path.exists():
        state = json.loads(path.read_text())
        if any(state.get(k) != v for k,v in binding.items()) or state.get('source_commit') not in (source_commit, *previous_commits) or not RUN_RE.fullmatch(state.get('run_id', '')):
            raise CollectionError('bootstrap_checkpoint_binding_changed')
    else:
        state = {'schema': 1, **binding, 'source_commit': source_commit, 'run_id': new_run_id(), 'stage': 'prepared'}
        if candidates:
            # Recovery from the pre-journal runner is permitted only for one
            # master path and its optional public pair, subsequently byte-hashed.
            masters = [r['object'] for r in candidates if r['object'].startswith('masters/') and r['object'].endswith('.sqlite3') and RUN_RE.fullmatch(r['object'][8:-8])]
            if not recover or len(masters) != 1:
                raise CollectionError('unreviewed_gcs_databases_preserved')
            state['run_id'] = masters[0][8:-8]
        save(path, state)
    permitted = {f"masters/{state['run_id']}.sqlite3", f"public/releases/{state['run_id']}/public.sqlite3"}
    if any(r['object'] not in permitted for r in candidates):
        raise CollectionError('unreviewed_gcs_databases_preserved')
    state['public_counts'] = counts
    state['transfer'] = {'chunk_bytes': UPLOAD_CHUNK_BYTES, 'connect_timeout_seconds': TRANSFER_TIMEOUT[0], 'io_timeout_seconds': TRANSFER_TIMEOUT[1], 'conditional_retry_seconds': 600}
    state['master_bytes'] = (work / 'master.sqlite3').stat().st_size
    state['public_bytes'] = (work / 'public.sqlite3').stat().st_size
    save(path, state)
    return state


def review_existing(store, state, work, candidates):
    """Read-only reconciliation precedes IAM/bootstrap writes."""
    for item in candidates:
        local = work / ('master.sqlite3' if item['object'].startswith('masters/') else 'public.sqlite3')
        # A hash mismatch refuses recovery and preserves all remote objects.
        ref = {'object': item['object'], 'generation': int(item['generation']), 'sha256': sha256(local)}
        checked = work / 'remote-review.sqlite3'
        store.download(ref, checked)
        checked.unlink()


def verify_registered(store, head, generation, work, expected_sha256, source_commit, *, previous_commits=(), bucket=None):
    """Resume after registration using only recorded objects; never rebuild/write."""
    path = work / 'bootstrap-progress.private.json'
    if not path.is_file():
        raise CollectionError('bootstrap_registration_receipt_missing')
    state = json.loads(path.read_text())
    if (state.get('schema') != 1 or state.get('stage') != 'registered'
            or state.get('input_master_sha256') != expected_sha256
            or state.get('bucket') != bucket
            or state.get('source_commit') not in (source_commit, *previous_commits)):
        raise CollectionError('bootstrap_registration_binding_changed')
    expected = {'schema': 1, 'qc': 'passed', 'run_id': state.get('run_id'),
        'source_commit': state.get('source_commit'), 'master': state.get('master'), 'public': state.get('public'),
        'report': {'bootstrap': True, 'input_master_sha256': state.get('input_master_sha256'),
                   'public_counts': state.get('public_counts'), 'proof': []}}
    validate_head(expected)
    if head != expected or any(state[key]['sha256'] != state.get(key + '_sha256') for key in ('master', 'public')):
        raise CollectionError('bootstrap_registration_head_changed')
    for key in ('master', 'public'):
        staged = work / (key + '.sqlite3')
        if not staged.is_file() or sha256(staged) != state[key]['sha256']:
            raise CollectionError('bootstrap_registered_file_changed')
    # Download exactly the receipt's generations and verify the actual bytes.
    # The staged DBs, receipt and state/current.json remain untouched.
    with tempfile.TemporaryDirectory(prefix='registered-check-', dir=work) as directory:
        for key in ('master', 'public'):
            store.download(state[key], Path(directory) / (key + '.sqlite3'))
    actual, observed_generation = store.read_head()
    if observed_generation != generation or actual != head:
        raise CollectionError('bootstrap_registration_head_changed')


def register(store, state, work):
    path = work / 'bootstrap-progress.private.json'
    run = state['run_id']
    if any(sha256(work / name) != state[field] for name,field in (('master.sqlite3','master_sha256'),('public.sqlite3','public_sha256'))):
        raise CollectionError('bootstrap_staged_file_changed')
    for key, local, name in (
        ('master', 'master.sqlite3', f'masters/{run}.sqlite3'),
        ('public', 'public.sqlite3', f'public/releases/{run}/public.sqlite3'),
    ):
        state['stage'] = key + '_upload'
        save(path, state)
        # Recovery uses immutable name + stored-byte hash, never overwrites.
        state[key] = store.upload_verified(work / local, name)
        state['stage'] = key + '_uploaded'
        save(path, state)
    head = {'schema': 1, 'qc': 'passed', 'run_id': run, 'source_commit': state['source_commit'], 'master': state['master'], 'public': state['public'], 'report': {'bootstrap': True, 'input_master_sha256': state['input_master_sha256'], 'public_counts': state['public_counts'], 'proof': []}}
    validate_head(head)
    state['stage'] = 'head_commit'
    save(path, state)
    try:
        store.commit(head, 0)
    except Exception as error:
        # A lost CAS response may already have committed this precise receipt.
        # A concurrent/different head is never replaced with a new generation.
        from google.api_core.exceptions import NotFound
        try:
            actual, _ = store.read_head()
        except NotFound:
            raise error
        if actual is None:
            raise error
        if actual != head:
            raise CollectionError('bootstrap_head_conflict') from None
    state['stage'] = 'registered'
    save(path, state)
    return head
