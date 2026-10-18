import copy
import json

import pytest

from conftest import make_pdf
from test_batch import all_config, fake_catalog
from tatemono_map.cloud.batch import execute_all
from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.fetch_public import fetch
from tatemono_map.cloud.public_db import readonly, sha256
from tatemono_map.cloud.republish import republish


def collected(store, config, tmp_path):
    cfg = all_config(config)
    a = make_pdf(tmp_path / 'a.pdf')
    b = make_pdf(tmp_path / 'b.pdf', rooms=('202',))
    work = tmp_path / 'collect'; work.mkdir()
    return execute_all(store, cfg, {}, work, 'a'*40, collector=fake_catalog(cfg, a, b)), cfg, a, b


def test_publish_only_keeps_snapshots_and_next_fresh_batch_uses_original_catalog(store, config, tmp_path):
    old, cfg, a, b = collected(store, config, tmp_path)
    before = store.read_head()
    work = tmp_path / 'publish'
    new = republish(store, work, 'b'*40, before[1])
    assert new['report']['collection_run_id'] == old['run_id']
    assert new['report']['company_catalog_ref'] == old['report']['company_catalog_ref']
    assert new['report']['company_results'] == old['report']['company_results']
    assert new['report']['newly_acquired_pdf_count'] == 0
    marker = fetch(store, tmp_path / 'pub.sqlite3', tmp_path / 'marker.json')
    assert marker['release_kind'] == 'publication_only'
    assert marker['collection_run_id'] == old['run_id']
    previous = tmp_path / 'previous.sqlite3'; store.download(old['master'], previous)
    with readonly(previous) as p, readonly(work / 'master.sqlite3') as c:
        for table in ['buildings', 'listings', 'sale_listings', 'raw_sources', 'current_ingest_snapshots']:
            assert p.execute(f'SELECT * FROM {table}').fetchall() == c.execute(f'SELECT * FROM {table}').fetchall()
    calls = []
    cfg['auto_seed_high_confidence'] = True
    b = make_pdf(tmp_path / 'next-new.pdf', building='次週新規マンション', address='福岡県北九州市小倉北区宇佐町9-8-7')
    collector = fake_catalog(cfg, a, b)
    def fresh(config, *args):
        calls.append(config['previous_verified_companies'])
        return collector(config, *args)
    nxt = tmp_path / 'next'; nxt.mkdir()
    result = execute_all(store, cfg, {}, nxt, 'b'*40, collector=fresh)
    assert calls and len(calls[0]) == 2
    assert result['report']['reused_companies'] == 0
    assert result['report']['newly_acquired_pdf_count'] == 2
    assert result['report']['new_buildings'] == 1
    with readonly(nxt / 'public.sqlite3') as c:
        new_id = c.execute("SELECT building_id FROM buildings WHERE canonical_name='次週新規マンション'").fetchone()[0]
    assert new_id in {p['building_key'] for p in result['report']['proof']}


@pytest.mark.parametrize('failure', ['generation', 'snapshot', 'evidence', 'cas'])
def test_publish_only_refuses_inconsistent_source_or_cas_without_moving_head(store, config, tmp_path, failure):
    old, *_ = collected(store, config, tmp_path)
    head, generation = store.read_head()
    if failure == 'snapshot':
        entry = head['report']['company_results'][0]
        ref, path = store.objects[entry['result_ref']['object']]
        value = json.loads(path.read_text()); value['ingest_run_id'] = -1
        path.write_text(json.dumps(value)); ref['sha256'] = sha256(path)
        entry['result_ref']['sha256'] = ref['sha256']
        store.head = copy.deepcopy(head)
    elif failure == 'evidence':
        store.head['report']['attached_rows'] += 1
    elif failure == 'cas':
        store.fail_commit = True
    before = store.read_head()
    with pytest.raises((CollectionError, RuntimeError)):
        republish(store, tmp_path / 'pub', 'b'*40, generation + (failure == 'generation'))
    assert store.read_head() == before
