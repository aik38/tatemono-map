import sqlite3
from pathlib import Path
import pytest
from tatemono_map.db.repo import connect
from tatemono_map.building_registry.merge import merge_confirmed
from tatemono_map.cloud.quality import plan, maintain
from tatemono_map.normalize.effective_rentals import effective_rentals


def seed(tmp_path):
    p=tmp_path/'master.sqlite3';c=connect(p)
    for key,name,addr in [('a','正しい建物','北九州市門司区大里1-2-3'),('b','正しい建物','福岡県北九州市門司区大里1丁目2番3号'),('c','別建物A棟','北九州市門司区大里1-2-3'),('d','別建物B棟','北九州市門司区大里1-2-3')]:
        c.execute('INSERT INTO buildings(building_id,canonical_name,canonical_address,norm_name,norm_address) VALUES (?,?,?,?,?)',(key,name,addr,name,addr))
    c.execute("INSERT INTO ingest_runs(id,source,snapshot_key,status) VALUES (1,'ulucks','test','completed')")
    c.execute("INSERT INTO current_ingest_snapshots(source,ingest_run_id) VALUES ('ulucks',1)")
    for key,b,room,rent,area in [('l1','a','101',50000,30),('l2','b','101',50000,30),('l3','b','102',60000,40)]:
        c.execute("INSERT INTO listings(listing_key,building_key,name,address,room_label,rent_yen,area_sqm,source_kind,ingest_run_id) VALUES (?,?, '正しい建物','北九州市門司区大里1-2-3',?,?,?,'ulucks',1)",(key,b,room,rent,area))
        c.execute("INSERT INTO building_sources(source,evidence_id,building_id,raw_name,raw_address) VALUES ('ulucks',?,?,'正しい建物','北九州市門司区大里1-2-3')",(key,b))
    for key in ('a','b'):c.execute('INSERT INTO building_summaries(building_key,vacancy_count) VALUES (?,1)',(key,))
    c.commit();return p,c


def test_confirmed_merge_preserves_sources_history_and_colliding_summaries(tmp_path):
    p,c=seed(tmp_path)
    with c:merge_confirmed(c,'a','b','test_confirmed')
    assert c.execute('SELECT COUNT(*) FROM listings').fetchone()[0]==3
    assert c.execute('SELECT COUNT(*) FROM building_sources').fetchone()[0]==3
    assert c.execute('SELECT COUNT(*) FROM building_sources WHERE building_id="a"').fetchone()[0]==3
    assert dict(c.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))['b']=='a'
    assert c.execute('SELECT COUNT(*) FROM buildings WHERE building_id="b"').fetchone()[0]==0
    assert len(effective_rentals(c))==2
    assert c.execute('SELECT old_row_json FROM quality_building_merges WHERE old_id="b"').fetchone()


def test_plan_merges_confirmed_group_while_leaving_separate_blocks(tmp_path):
    p,c=seed(tmp_path);result=plan(c)
    assert len(result['merges'])==1
    assert {result['merges'][0]['keep'],result['merges'][0]['drop']}=={'a','b'}
    assert c.execute('SELECT COUNT(*) FROM buildings').fetchone()[0]==4


def test_missing_price_alone_is_preserved_and_anonymous_bad_row_is_excluded(tmp_path):
    p,c=seed(tmp_path)
    c.execute("UPDATE listings SET rent_yen=NULL WHERE listing_key='l1'")
    c.execute("INSERT INTO listings(listing_key,building_key,room_label,layout,source_kind,ingest_run_id) VALUES ('bad','c','','54.78m2','mansion_review_chintai',1)")
    c.commit();rows=effective_rentals(c)
    assert any(r['listing_key']=='l1' for r in rows)
    assert not any(r['listing_key']=='bad' for r in rows)


def test_merge_rejects_canonical_alias_reversal(tmp_path):
    p,c=seed(tmp_path)
    c.execute("INSERT INTO building_key_aliases(alias_key,canonical_key) VALUES ('a','b')");c.commit()
    with pytest.raises(ValueError,match='target_is_alias'):
        with c:merge_confirmed(c,'a','b','wrong_direction')
    assert c.execute('SELECT COUNT(*) FROM buildings').fetchone()[0]==4
