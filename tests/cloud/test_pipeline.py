from __future__ import annotations

import copy
import shutil
import sqlite3
from pathlib import Path

import pytest

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.fetch_public import fetch
from tatemono_map.cloud.pipeline import scope_key, update_master, validate_master
from tatemono_map.cloud.public_db import readonly, sha256, validate_public
from tatemono_map.cloud.run import execute
from tatemono_map.cloud.storage import commit_release
from tatemono_map.db.repo import connect
from conftest import make_pdf


def test_real_parser_to_master_public_and_pages_input(store, config, pdf, tmp_path):
    work = tmp_path / "run"
    work.mkdir()
    result = execute(store, config, {}, work, "b" * 40, collector=lambda *_: ([pdf], 1))
    assert result["report"]["parsed_rows"] == result["report"]["attached_rows"] == 1
    assert result["report"]["pdf_count"] == 1
    assert any(name.startswith("backups/") for name in store.objects)
    with readonly(work / "master.sqlite3") as conn:
        assert conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE listing_key='legacy-b'").fetchone()[0] == 1
        assert conn.execute("SELECT SUM(vacancy_count) FROM building_summaries").fetchone()[0] == 2
        assert set(row[0] for row in conn.execute("SELECT source FROM current_ingest_snapshots")) == {"legacy-bootstrap", scope_key(config)}
    store.downloads.clear()
    public = tmp_path / "pages.sqlite3"
    marker = fetch(store, public, tmp_path / "release.json")
    assert store.downloads == [result["public"]["object"]]
    assert marker["public_sha256"] == sha256(public)
    assert marker["proof"][0]["vacancy_count"] == 1
    with readonly(public) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name IN ('listings','raw_sources','ingest_runs','cloud_scope_bindings')").fetchone()
    # Existing renderer is exercised by a separate subprocess smoke test below.


def test_scoped_replacement_does_not_remove_other_company_or_source(master, config, pdf, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    first = update_master(master, [pdf], 1, config, a, "first")
    other_config = {**config, "company_id": "company-b", "company_label": "架空管理会社B"}
    other_pdf = make_pdf(tmp_path / "ulucks-other.pdf", rooms=("202",))
    second = update_master(master, [other_pdf], 1, other_config, b, "second")
    new_pdf = make_pdf(tmp_path / "ulucks-new.pdf", rent="6.5万円", rooms=("102",))
    update_master(master, [new_pdf], 1, config, a, "third")
    with readonly(master) as conn:
        current = dict(conn.execute("SELECT source,ingest_run_id FROM current_ingest_snapshots"))
        assert current[scope_key(other_config)] == second["ingest_run_id"]
        assert current[scope_key(config)] != first["ingest_run_id"]
        rows = conn.execute("SELECT room_label,rent_yen FROM listings WHERE ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots) AND source_kind='ulucks'").fetchall()
        assert sorted(rows) == [("102", 65000), ("202", 55000)]
        # Historical successful snapshot is still intact.
        assert conn.execute("SELECT room_label FROM listings WHERE ingest_run_id=?", (first["ingest_run_id"],)).fetchone()[0] == "101"
        assert conn.execute("SELECT rent_yen FROM listings WHERE listing_key='legacy-b'").fetchone()[0] == 70000
        assert conn.execute("SELECT COUNT(*) FROM building_sources WHERE source='ulucks'").fetchone()[0] == 3


@pytest.mark.parametrize("failure", ["download", "parser", "backup", "public_upload", "cas"])
def test_failure_never_moves_master_or_public_head(store, config, pdf, tmp_path, failure):
    original, generation = store.read_head()
    original_bytes = store.objects[original["master"]["object"]][1].read_bytes()
    work = tmp_path / "failed"
    work.mkdir()
    def collector(*_):
        if failure == "download":
            raise CollectionError("simulated_login_failure")
        return [pdf], (2 if failure == "parser" else 1)
    if failure == "backup":
        store.fail_upload_prefix = "backups/"
    elif failure == "public_upload":
        store.fail_upload_prefix = "public/"
    elif failure == "cas":
        store.fail_commit = True
    with pytest.raises(Exception):
        execute(store, config, {}, work, "b" * 40, collector=collector)
    assert store.read_head() == (original, generation)
    assert store.objects[original["master"]["object"]][1].read_bytes() == original_bytes


def test_public_database_is_never_accepted_as_master(store, tmp_path):
    public = store.objects[store.head["public"]["object"]][1]
    before = sha256(public)
    with pytest.raises(CollectionError, match="not_a_master|vacancy_history_empty"):
        validate_master(public)
    assert sha256(public) == before


def test_public_validator_rejects_private_tables(store, tmp_path):
    public = tmp_path / "public.sqlite3"
    shutil.copyfile(store.objects[store.head["public"]["object"]][1], public)
    with sqlite3.connect(public) as conn:
        conn.execute("CREATE TABLE raw_sources (content TEXT)")
    with pytest.raises(ValueError, match="unexpected_public"):
        validate_public(public)


def test_legacy_baseline_adoption_preserves_other_ulucks(master, config, pdf, tmp_path):
    with connect(master) as conn:
        building = conn.execute("SELECT building_id FROM buildings WHERE canonical_name='架空テストマンション'").fetchone()[0]
        for key, room in (("old-a", "101"), ("old-other-company", "999")):
            conn.execute("INSERT INTO listings(listing_key,building_key,name,address,room_label,rent_yen,source_kind) VALUES (?,?,'架空テストマンション','福岡県北九州市小倉北区魚町1-1-1',?,50000,'ulucks')", (key,building,room))
    config["baseline_listing_keys"] = ["old-a"]
    update_master(master, [pdf], 1, config, tmp_path, "first")
    with readonly(master) as conn:
        assert conn.execute("SELECT vacancy_count FROM building_summaries WHERE building_key=?", (building,)).fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE listing_key IN ('old-a','old-other-company')").fetchone()[0] == 2


def test_same_pdf_repeated_does_not_steal_previous_run_rows(master, config, pdf, tmp_path):
    first = update_master(master, [pdf], 1, config, tmp_path, "one")
    second = update_master(master, [pdf], 1, config, tmp_path, "two")
    assert first["ingest_run_id"] != second["ingest_run_id"]
    with readonly(master) as conn:
        for result in (first, second):
            assert conn.execute("SELECT COUNT(*) FROM listings WHERE ingest_run_id=?", (result["ingest_run_id"],)).fetchone()[0] == 1


def test_out_of_area_and_count_drop_rejected(master, config, pdf, tmp_path):
    update_master(master, [pdf], 1, config, tmp_path, "first")
    wrong = {**config, "address_contains": "門司区"}
    with pytest.raises(CollectionError, match="out_of_scope"):
        update_master(master, [pdf], 1, wrong, tmp_path, "bad")
    two = make_pdf(tmp_path / "two.pdf", rooms=("101", "102"))
    update_master(master, [two], 2, config, tmp_path, "two")
    with pytest.raises(CollectionError, match="drop_exceeds"):
        update_master(master, [pdf], 1, config, tmp_path, "drop")


def test_authenticated_confirmed_zero_replaces_only_that_scope(store, config, pdf, tmp_path):
    from tatemono_map.cloud.collector import Collected
    first = tmp_path / "positive"
    zero = tmp_path / "zero"
    first.mkdir(); zero.mkdir()
    execute(store, config, {}, first, "a" * 40, collector=lambda *_: ([pdf], 1))
    result = execute(store, config, {}, zero, "b" * 40, collector=lambda *_: Collected([], 0, True, {"search_counts": [0, 0], "scope_verified": True}))
    assert result["report"]["acquisition_status"] == "confirmed_zero"
    assert result["report"]["attached_rows"] == 0
    assert result["report"]["proof"][0]["vacancy_count"] == 0
    with readonly(zero / "master.sqlite3") as conn:
        assert conn.execute("SELECT SUM(vacancy_count) FROM building_summaries").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE listing_key='legacy-b'").fetchone()[0] == 1
    marker = fetch(store, tmp_path / "zero-public.sqlite3", tmp_path / "zero-marker.json")
    assert marker["proof"][0]["vacancy_count"] == 0


def test_unconfirmed_zero_does_not_publish(store, config, tmp_path):
    original = store.read_head()
    work = tmp_path / "bad-zero"
    work.mkdir()
    with pytest.raises(CollectionError, match="no_confirmed"):
        execute(store, config, {}, work, "a" * 40, collector=lambda *_: ([], 0))
    assert store.read_head() == original


def test_uploaded_style_public_with_empty_private_scaffolding_is_rejected(master):
    with connect(master) as conn:
        conn.execute("DELETE FROM listings")
    with pytest.raises(CollectionError, match="vacancy_history_empty"):
        validate_master(master)


def test_existing_renderer_produces_proof_matching_json(store, config, pdf, tmp_path, monkeypatch):
    # Drive the public CLI to preserve the same options/entrypoint as Pages.
    import subprocess, sys, os, json
    work = tmp_path / "render-run"
    work.mkdir()
    execute(store, config, {}, work, "a" * 40, collector=lambda *_: ([pdf], 1))
    public = tmp_path / "render-public.sqlite3"
    marker = fetch(store, public, tmp_path / "marker.json")
    dist = tmp_path / "dist"
    subprocess.run([sys.executable, "-m", "tatemono_map.render.build", "--db-path", str(public), "--output-dir", str(dist), "--version", "v2"], check=True, capture_output=True, env={**os.environ, "PYTHONPATH": "src", "TATEMONO_MAP_SITE_URL": "https://www.tatemono-map.com", "TATEMONO_MAP_BASE_PATH": ""})
    from tatemono_map.cloud.verify_public import compare
    compare(marker, json.loads((dist / "data/buildings.json").read_text()))
    assert (dist / "index.html").is_file()


def test_committed_wal_pages_are_included_in_uploaded_standalone_master(store, master, tmp_path):
    from tatemono_map.cloud.public_db import export_public, validate_public
    work = tmp_path / "wal-run"
    work.mkdir()
    shutil.copyfile(master, work / "master.sqlite3")
    export_public(work / "master.sqlite3", work / "public.sqlite3")
    held = sqlite3.connect(work / "master.sqlite3")
    try:
        assert held.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        held.execute("INSERT INTO raw_sources(provider,source_kind,source_url,content) VALUES ('ulucks','master','file:test','wal-only-private-marker')")
        held.commit()
        assert (work / "master.sqlite3-wal").stat().st_size > 0
        result = commit_release(store, work, "20261016T010101Z-111111111111", store.generation, {"public_counts": validate_public(work / "public.sqlite3")}, "a" * 40)
        uploaded = store.objects[result["master"]["object"]][1]
        with readonly(uploaded) as conn:
            assert conn.execute("SELECT COUNT(*) FROM raw_sources WHERE content='wal-only-private-marker'").fetchone()[0] == 1
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        held.close()
