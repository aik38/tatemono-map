from __future__ import annotations
import json
import pytest
from selectolax.parser import HTMLParser
from tatemono_map.cloud.mansion_parser import parse_rows,money,page_info
from tatemono_map.cloud.mansion_geography import AREAS,MUNICIPALITIES
from tatemono_map.db.repo import connect
from tatemono_map.normalize.effective_rentals import effective_rentals
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.cloud.mansion_integrate import schema


def test_all_publication_municipalities_are_explicit():
    assert len(AREAS)==22 and len(MUNICIPALITIES)==len(set(MUNICIPALITIES))==35
    assert {'田川郡大任町','田川郡赤村'}<=set(MUNICIPALITIES)


def test_current_colspan_shape_does_not_shift_rent_area_or_floor():
    html='''<table><tr><th colspan="3" class="size_title">賃貸情報</th><th>賃料(管理費)</th><th>敷金</th><th>礼金</th><th>専有面積</th><th>間取り</th><th>所在階</th><th>向き</th></tr>
    <tbody class="recommend_row"><tr><td><img></td><td><a href="https://www.mansion-review.jp/chintai/1328250038770.html">FLATS別院 401</a></td><td>6.7万円<br>(4,000円)</td><td>無</td><td>2ヶ月</td><td>36.57m²</td><td>1LDK</td><td>4階</td><td>南西</td><td>情報取得日</td></tr></tbody></table>'''
    t=HTMLParser(html);row=parse_rows(t.css_first('table'),t.css('tbody.recommend_row tr'),{'building_name':'FLATS別院','address':'福岡県北九州市門司区原町別院10番8号','building_url':'https://www.mansion-review.jp/mansion/2280294.html'},'chintai','list')[0]
    assert (row['price_yen'],row['fee_yen'],row['area_sqm'],row['floor'],row['room'])==(67000,4000,36.57,'4階','401')
    assert not row['reason']


@pytest.mark.parametrize('value',['2,000万円台','非公開','応相談','無料会員登録でモザイクを消す','-円'])
def test_hidden_price_is_never_numeric(value):
    assert money(value) is None


def priority_db(tmp_path,counts=(5,8,10),legacy=True):
    path=tmp_path/'priority.sqlite3';c=connect(path)
    c.execute("INSERT INTO buildings(building_id,canonical_name,canonical_address) VALUES ('b','優先順位確認','福岡県北九州市門司区大里1-2-3')")
    for i,(source,n) in enumerate(zip(('ulucks','realpro','mansion_review_chintai'),counts),1):
        c.execute("INSERT INTO ingest_runs(id,source,snapshot_key,status) VALUES (?,?,?,'completed')",(i,source,source))
        c.execute('INSERT INTO current_ingest_snapshots(source,ingest_run_id) VALUES (?,?)',(source,i))
        for j in range(n):
            c.execute("INSERT INTO listings(listing_key,building_key,room_label,rent_yen,area_sqm,source_kind,ingest_run_id) VALUES (?,'b',?,?,?,?,?)",(source+str(j),str(101+j),50000+i*10000,20+i,source,i))
    if legacy:c.execute("INSERT INTO listings(listing_key,building_key,room_label,rent_yen,area_sqm,source_kind,ingest_run_id) VALUES ('legacy','b','999',99999,99,'master',1)")
    c.commit();return path,c


@pytest.mark.parametrize('counts,source,n',[((5,8,10),'ulucks',5),((0,5,10),'realpro',5),((0,0,10),'mansion_review_chintai',10)])
def test_entire_canonical_building_uses_one_provider(tmp_path,counts,source,n):
    path,c=priority_db(tmp_path,counts)
    rows=effective_rentals(c)
    assert len(rows)==n and {r['source_kind'] for r in rows}=={source}
    assert len({r['rent_yen'] for r in rows})==1
    assert len({r['area_sqm'] for r in rows})==1
    # No rows is only lack of valid offers, not an observed zero assertion.
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='confirmed_zero_buildings'").fetchone()


def test_mr_sale_successful_zero_expires_only_its_owned_history(tmp_path):
    path,c=priority_db(tmp_path,legacy=False);schema(c)
    c.execute("INSERT INTO sale_listings(sale_listing_key,building_key,source,price_yen,area_sqm,ingest_run_id) VALUES ('old','b','mansion_review_mansion',10000000,60,1)")
    c.execute("INSERT INTO mansion_review_sale_ownership VALUES ('old','mansion_review:mansion:1616')")
    c.execute("INSERT INTO mansion_review_sale_buildings VALUES ('b','mansion_review:mansion:1616')")
    c.commit();rebuild(str(path))
    assert c.execute("SELECT sale_listing_count FROM building_summaries WHERE building_key='b'").fetchone()[0]==1
    c.execute("INSERT INTO current_ingest_snapshots(source,ingest_run_id) VALUES ('mansion_review:mansion:1616',3)")
    c.commit();rebuild(str(path))
    assert not c.execute("SELECT sale_listing_count FROM building_summaries WHERE building_key='b'").fetchone()[0]
    assert c.execute('SELECT COUNT(*) FROM sale_listings').fetchone()[0]==1


def test_error_page_is_not_zero():
    with pytest.raises(ValueError,match='wrong_municipality'):
        page_info('<h1>Server error</h1>','chintai','1616','北九州市門司区')
