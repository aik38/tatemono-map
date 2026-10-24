import csv
import pytest
from tatemono_map.db.repo import connect
from tatemono_map.building_registry.normalization import normalize_building_input
from tatemono_map.building_registry.ingest_master_import import (
    MASTER_COLUMNS, _can_auto_seed, _mansion_review_space_match, ingest_master_import_csv,
)


def building(c, bid='b', name='Nest Piece 原町', address='福岡県北九州市門司区大里原町2-7'):
    n = normalize_building_input(name, address)
    c.execute('INSERT INTO buildings(building_id,canonical_name,canonical_address,norm_name,norm_address) VALUES (?,?,?,?,?)',
              (bid, name, address, n.normalized_name, n.normalized_address))
    c.commit()


@pytest.mark.parametrize('source,allowed', [('mansion_review_chintai',True),('mansion_review_mansion',True),('ulucks',False),('master',False)])
def test_attached_first_lot_is_source_scoped(tmp_path, source, allowed):
    with connect(tmp_path/'db') as c:
        assert _can_auto_seed(c,'FLATS別院','北九州市門司区原町別院10-8','unmatched',source)[0] is allowed


@pytest.mark.parametrize('address', ['北九州市門司区原町別院','北九州市門司区原町別院10','北九州市門司区原町別院10-8〜10','北九州市門司区原町別院10-8、12','北九州市門司区原町別院10-8付近'])
def test_incomplete_lots_stay_held(tmp_path,address):
    with connect(tmp_path/'db') as c:
        assert not _can_auto_seed(c,'FLATS別院',address,'unmatched','mansion_review_mansion')[0]


def test_whitespace_requires_one_canonical_and_exact_address(tmp_path):
    with connect(tmp_path/'db') as c:
        building(c)
        n=normalize_building_input('NestPiece原町','北九州市門司区大里原町2番7号')
        assert _mansion_review_space_match(c,n,'b')
        assert not _mansion_review_space_match(c,normalize_building_input('NestPiece原町II',n.raw_address),'b')
        assert not _mansion_review_space_match(c,normalize_building_input(n.raw_name,'北九州市門司区大里原町2-8'),'b')
        building(c,'other','NestPiece原町')
        assert not _mansion_review_space_match(c,n,'b')


@pytest.mark.parametrize('source,expected', [('mansion_review',1),('realpro',0),('ulucks',0)])
def test_importer_allows_only_mr_whitespace(tmp_path,source,expected):
    db=tmp_path/'db'
    with connect(db) as c: building(c)
    row={k:'' for k in MASTER_COLUMNS}
    row.update(category='chintai',building_name='NestPiece原町',address='北九州市門司区大里原町2-7',room='101',rent_man='6',area_sqm='30',page='https://example.com/1',evidence_id='test')
    path=tmp_path/'rows.csv'
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=MASTER_COLUMNS);w.writeheader();w.writerow(row)
    ingest_master_import_csv(str(db),str(path),source=source,snapshot_source='test',snapshot_key='test',strict_name_match=True,exact_name_match=True)
    with connect(db) as c:
        assert c.execute('SELECT COUNT(*) FROM listings').fetchone()[0]==expected
        assert c.execute('SELECT COUNT(*) FROM buildings').fetchone()[0]==1


@pytest.mark.parametrize('conflict',[False,True])
def test_saved_rejudgment_keeps_snapshots_upstream_and_sales(master,tmp_path,conflict):
    import json
    from tatemono_map.cloud.mansion_integrate import schema
    from tatemono_map.cloud.mansion_limited import prepare
    from tatemono_map.cloud.public_db import export_public, snapshot_sqlite
    from tatemono_map.normalize.building_summaries import rebuild
    from tatemono_map.normalize.effective_rentals import effective_rentals
    scope='mansion_review:chintai:1616'
    targets=[]
    with connect(master) as c:
        schema(c)
        building(c)
        c.execute("INSERT INTO ingest_runs(id,source,snapshot_key,status) VALUES (1,'realpro','old','completed'),(2,?,'old','completed')",(scope,))
        c.execute("UPDATE listings SET ingest_run_id=1")
        c.execute("INSERT INTO current_ingest_snapshots(source,ingest_run_id) VALUES ('realpro',1),(?,2)",(scope,))
        c.execute("INSERT INTO mansion_review_scopes VALUES (?,'北九州市門司区','chintai',2,'saved')",(scope,))
        c.execute("INSERT INTO sale_listings(sale_listing_key,building_key,source,price_yen,area_sqm,ingest_run_id) VALUES ('old-sale','b','mansion_review_mansion',10000000,60,2)")
        for index in range(2 if conflict else 1):
            raw=dict(building_name='NestPiece原町',address='福岡県北九州市門司区大里原町2-7',
                building_url='https://www.mansion-review.jp/mansion/1.html',kind='chintai',
                source_url=f'https://www.mansion-review.jp/chintai/{index}.html',
                page_url='saved',room='101',price_yen=60000+index*1000,fee_yen=3000,area_sqm=30,
                floor='1階',layout='1LDK',built_raw='',structure='',access='',floor_count='',
                total_units='',deposit='',key_money='',direction='南',reason='',raw='saved evidence')
            evidence=f'saved-{index}';raw_json=json.dumps(raw,ensure_ascii=False)
            c.execute("INSERT INTO mansion_review_rows VALUES (?,2,?,'held','unresolved_canonical_match',NULL,NULL,?)",(scope,evidence,raw_json))
            targets.append(dict(scope_key=scope,ingest_run_id=2,evidence_id=evidence,raw_json=raw_json,cause='name_whitespace'))
        protected={r['listing_key']:r for r in effective_rentals(c) if r['source_kind']=='realpro'}
        snapshots=dict(c.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots'))
    rebuild(str(master))
    baseline=tmp_path/'baseline.sqlite3';export_public(master,baseline)
    original=tmp_path/'original.sqlite3';snapshot_sqlite(master,original)
    report=prepare(master,baseline,targets,tmp_path,'test-operation',baseline_master=original)
    assert report['row_counts'].get('accepted_existing',0)==(0 if conflict else 1)
    assert report['row_counts'].get('held',0)==(2 if conflict else 0)
    assert report['new_buildings']==0
    with connect(master) as c:
        assert dict(c.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots'))==snapshots
        assert {r['listing_key']:r for r in effective_rentals(c) if r['source_kind']=='realpro'}==protected
        assert c.execute("SELECT COUNT(*) FROM sale_listings WHERE sale_listing_key='old-sale'").fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM mansion_review_rows WHERE classification=?',('held',)).fetchone()[0]==len(targets)
        assert c.execute('SELECT COUNT(*) FROM listings WHERE ingest_run_id=2').fetchone()[0]==(0 if conflict else 1)
