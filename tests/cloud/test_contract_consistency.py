"""Synthetic end-to-end regressions for the audited data boundaries."""
import json
import sqlite3

import pytest

from tatemono_map.cloud.pipeline import update_master
from tatemono_map.cloud.public_db import export_public, readonly
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.render.build import _load_buildings
from test_pipeline import add_unknown_legacy


def target_rows(path):
    return next(b for b in _load_buildings(str(path))[0] if b['name'] == '架空テストマンション')


def test_summary_private_render_and_public_render_select_identical_units(master, config, pdf, tmp_path):
    building = add_unknown_legacy(master, ['101', '999'])
    with connect(master) as conn:
        # Stale duplicate has deliberately different terms; it must disappear
        # from display as well as vacancy counts, without deleting its history.
        conn.execute("UPDATE listings SET deposit_text='9ヶ月',key_money_text='8ヶ月',rent_yen=990000 WHERE listing_key='unknown-0'")
        conn.execute("UPDATE listings SET deposit_text='なし',key_money_text='1ヶ月',maint_yen=2000,area_sqm=30,layout='2K',floor_text='9階' WHERE listing_key='unknown-1'")
        for source in ('realpro','mansion_review_chintai'):
            conn.execute("INSERT INTO listings(listing_key,building_key,name,address,room_label,rent_yen,deposit_text,source_kind) VALUES (?,?, '架空テストマンション','福岡県北九州市小倉北区魚町1-1-1','998',880000,'7ヶ月',?)", (source,building,source))
    result = update_master(master, [pdf], 1, config, tmp_path, 'contract')
    assert result['legacy_overlap_rows'] == 1
    assert result['counts_after']['buildings'] == result['counts_before']['buildings']
    assert result['counts_after']['listings'] == result['counts_before']['listings'] + 1
    assert result['pdfs'][0]['pages'] == 1
    with readonly(tmp_path/'public.sqlite3') as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name IN ('listings','raw_sources','building_sources')").fetchall()
    private = target_rows(master)
    public = target_rows(tmp_path/'public.sqlite3')
    for row in (private, public):
        assert row['vacancy_count'] == 2
        assert row['rent_yen_min'] == 50000
        assert row['rent_yen_max'] == 55000
        assert row['rental_deposit_label'] == 'なし'
        assert row['rental_key_money_label'] == '1ヶ月'
        assert max(row['rental_current']['rents']) == 55000
        assert set(row['rental_current']['layouts']) == {'1K','2K'}
        assert set(row['rental_current']['floors']) == {'9階'}
    with readonly(master) as conn:
        assert conn.execute("SELECT rent_yen FROM listings WHERE listing_key='unknown-0'").fetchone()[0] == 990000



def test_unknown_room_on_unaffected_building_preserved(master, config, pdf, tmp_path):
    with connect(master) as conn:
        building = conn.execute("SELECT building_id FROM buildings WHERE canonical_name='他社テストマンション'").fetchone()[0]
        conn.execute("INSERT INTO listings(listing_key,building_key,name,address,room_label,rent_yen,source_kind) VALUES ('unrelated-unknown',?,'他社テストマンション','福岡県北九州市小倉北区別町1-1-1',NULL,60000,'ulucks')", (building,))
    update_master(master, [pdf], 1, config, tmp_path, 'unaffected')
    with readonly(master) as conn:
        assert conn.execute("SELECT room_label FROM listings WHERE listing_key='unrelated-unknown'").fetchone()[0] is None


def test_preflight_unknown_rooms_are_not_equivalence_claims(master, tmp_path, monkeypatch):
    from test_setup import module
    from tatemono_map.cloud.public_db import sha256
    add_unknown_legacy(master, ['不明'])
    mod = module('initial_release')
    actual = mod.audit(master)
    monkeypatch.setattr(mod, 'EXPECTED', sha256(master))
    monkeypatch.setattr(mod, 'FINGERPRINT', actual['canonical_id_fingerprint'])
    review = tmp_path/'review.json'
    review.write_text(json.dumps({'selected':actual,'ulucks_total_rows':4006,'kokurakita_rows':[{}]*2195,'ownership_decided':False}))
    assert mod.check_inputs(master, review)['sha256'] == actual['sha256']
    # The existing publication-blocking regression for touched unknown rooms
    # remains in test_pipeline; preflight cannot decide which buildings overlap.


def test_alias_chain_shares_the_rental_selection_and_preserves_sale(master):
    with connect(master) as conn:
        building = conn.execute("SELECT building_id FROM buildings WHERE canonical_name='架空テストマンション'").fetchone()[0]
        conn.execute("INSERT INTO building_key_aliases(alias_key,canonical_key) VALUES ('alias-one','alias-two'),('alias-two',?)", (building,))
        for source,key,rent in [('ulucks','alias-one',55000),('realpro',building,90000),('mansion_review_chintai',building,80000)]:
            conn.execute("INSERT INTO listings(listing_key,building_key,name,address,room_label,rent_yen,source_kind) VALUES (?,?, '架空テストマンション','福岡県北九州市小倉北区魚町1-1-1','101',?,?)",(source,key,rent,source))
        conn.execute("INSERT INTO sale_listings(sale_listing_key,building_key,price_yen,source) VALUES ('sale',?,12000000,'mansion_review_mansion')",(building,))
    rebuild(str(master))
    row = target_rows(master)
    assert row['vacancy_count'] == 1
    assert row['rental_current']['rents'] == [55000]
    assert row['sale_listing_count'] == 1
