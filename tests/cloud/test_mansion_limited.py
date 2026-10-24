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
