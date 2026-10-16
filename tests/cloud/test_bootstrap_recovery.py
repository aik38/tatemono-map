import copy,json
from pathlib import Path

import pytest
from google.api_core.exceptions import NotFound

from conftest import MemoryStore
from tatemono_map.cloud.bootstrap import prepare,register,review_existing
from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.public_db import sha256,snapshot_sqlite


def candidates(store):
    return [{'object':name,'generation':ref['generation']} for name,(ref,path) in store.objects.items() if name.endswith('.sqlite3')]


def test_registration_resumes_public_upload_failure_without_new_master_or_run(master,tmp_path):
    store=MemoryStore(tmp_path/'objects');work=tmp_path/'bootstrap'
    before=sha256(master)
    state=prepare(master,before,work,'a'*40)
    store.fail_upload_prefix='public/'
    with pytest.raises(RuntimeError,match='upload failure'):register(store,state,work)
    assert store.head is None
    assert len(store.objects)==1
    progress=json.loads((work/'bootstrap-progress.private.json').read_text())
    assert progress['stage']=='public_upload'
    store.fail_upload_prefix=None
    resumed=prepare(master,before,work,'a'*40,candidates=candidates(store),recover=True)
    assert resumed['run_id']==state['run_id']
    review_existing(store,resumed,work,candidates(store))
    result=register(store,resumed,work)
    assert len(store.objects)==2
    assert result['run_id']==state['run_id']
    assert result['report']['input_master_sha256']==before==sha256(master)
    assert json.loads((work/'bootstrap-progress.private.json').read_text())['stage']=='registered'


def test_lost_head_response_is_reconciled_without_overwriting_a_different_head(master,tmp_path):
    class LostAck(MemoryStore):
        def commit(self,head,generation):
            super().commit(head,generation)
            raise ConnectionError('reply lost')
    store=LostAck(tmp_path/'objects');work=tmp_path/'bootstrap'
    state=prepare(master,sha256(master),work,'a'*40)
    result=register(store,state,work)
    assert result==store.head
    assert register(store,state,work)==result
    assert len(store.objects)==2
    winner={**store.head,'source_commit':'b'*40}
    store.head=copy.deepcopy(winner)
    with pytest.raises(CollectionError,match='head_conflict'):register(store,state,work)
    assert store.head==winner


def test_pre_journal_master_is_adopted_only_after_exact_stored_byte_verification(master,tmp_path):
    store=MemoryStore(tmp_path/'objects')
    original=tmp_path/'normalized';snapshot_sqlite(master,original)
    run='20261016T123500Z-012345abcdef'
    store.upload(original,f'masters/{run}.sqlite3')
    with pytest.raises(CollectionError,match='unreviewed'):
        prepare(master,sha256(master),tmp_path/'fresh','b'*40,candidates=candidates(store))
    work=tmp_path/'recovery'
    state=prepare(master,sha256(master),work,'b'*40,candidates=candidates(store),recover=True)
    assert state['run_id']==run
    review_existing(store,state,work,candidates(store))
    result=register(store,state,work)
    assert result['run_id']==run and len(store.objects)==2


def test_same_path_with_foreign_database_bytes_is_preserved_and_refused(master,tmp_path):
    store=MemoryStore(tmp_path/'objects');foreign=tmp_path/'foreign';foreign.write_bytes(b'foreign-db')
    store.upload(foreign,'masters/20261016T123500Z-012345abcdef.sqlite3')
    work=tmp_path/'recovery'
    state=prepare(master,sha256(master),work,'b'*40,candidates=candidates(store),recover=True)
    with pytest.raises(AssertionError):review_existing(store,state,work,candidates(store))
    assert store.head is None and len(store.objects)==1
    assert next(iter(store.objects.values()))[1].read_bytes()==b'foreign-db'


def test_unknown_gcs_database_path_never_becomes_a_bootstrap_candidate(master,tmp_path):
    with pytest.raises(CollectionError,match='unreviewed'):
        prepare(master,sha256(master),tmp_path/'recovery','a'*40,candidates=[{'object':'old/private.db','generation':1}],recover=True)


def test_journal_binds_unchanged_input_and_allows_only_explicit_previous_code(master,tmp_path):
    work=tmp_path/'bootstrap'
    first=prepare(master,sha256(master),work,'a'*40)
    with pytest.raises(CollectionError,match='binding_changed'):
        prepare(master,sha256(master),work,'b'*40)
    fixed=prepare(master,sha256(master),work,'b'*40,previous_commits=['a'*40])
    assert fixed['run_id']==first['run_id'] and fixed['source_commit']=='a'*40
    (work/'master.sqlite3').write_bytes(b'unexpected replacement')
    store=MemoryStore(tmp_path/'objects')
    with pytest.raises(CollectionError,match='staged_file_changed'):register(store,fixed,work)
    assert store.objects=={}
