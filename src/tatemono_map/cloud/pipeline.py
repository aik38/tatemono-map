"""Update a disposable copy of the master; only the GCS head CAS commits it."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from tatemono_map.building_registry.ingest_master_import import ingest_master_import_csv, set_current_snapshot
from tatemono_map.cli.pdf_batch_run import UlucksParser, qc_check, write_master_import_csv
from tatemono_map.cloud.collector import CollectionError, normal
from tatemono_map.cloud.public_db import export_public, readonly
from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import rebuild


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def scope_key(config: dict) -> str:
    return "ulucks:" + digest({k: config[k] for k in ("login_url", "company_id", "area_id")})[:32]


def validate_master(path: Path) -> None:
    # Must precede connect()/ensure_schema: never turn a public DB into a master.
    with readonly(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"buildings", "listings", "raw_sources", "ingest_runs", "current_ingest_snapshots"} <= tables:
            raise CollectionError("source_is_not_a_master_database")
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise CollectionError("master_integrity_failed")
        if conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0] <= 0:
            raise CollectionError("master_canonical_buildings_empty")
        if conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] <= 0:
            # The supplied public DB has empty private-schema scaffolding too.
            # Table presence alone cannot establish that it is a genuine master.
            raise CollectionError("master_vacancy_history_empty")
        if conn.execute("SELECT COUNT(*) FROM current_ingest_snapshots c LEFT JOIN ingest_runs r ON r.id=c.ingest_run_id WHERE r.status IS NULL OR r.status!='completed'").fetchone()[0]:
            raise CollectionError("master_current_run_not_completed")
        if "source_priority" not in tables:
            raise CollectionError("master_priority_contract_missing")
        priority = dict(conn.execute("SELECT source,priority_rank FROM source_priority WHERE domain='rental' AND enabled=1"))
        ranks = [priority.get(source) for source in ("ulucks", "realpro", "mansion_review_chintai")]
        if any(rank is None for rank in ranks) or not ranks[0] < ranks[1] < ranks[2]:
            raise CollectionError("master_rental_priority_contract_invalid")


def _prepare_scope(conn, config: dict, key: str) -> None:
    identity = digest({k: config[k] for k in ("company_id", "company_label", "area_id", "area_label", "address_contains")})
    baseline_keys = sorted(set(config["baseline_listing_keys"]))
    baseline = digest(baseline_keys)
    binding = conn.execute("SELECT identity_sha256, baseline_sha256 FROM cloud_scope_bindings WHERE scope_key=?", (key,)).fetchone()
    if binding:
        if tuple(binding) != (identity, baseline):
            raise CollectionError("scope_identity_or_baseline_changed")
        return
    # Preserve formerly active legacy rows before adding the first current pointer.
    if not conn.execute("SELECT 1 FROM current_ingest_snapshots").fetchone():
        conn.execute("INSERT INTO ingest_runs(source,snapshot_key,status,finished_at) VALUES ('legacy-bootstrap',?,'completed',CURRENT_TIMESTAMP)", (uuid.uuid4().hex,))
        run = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE listings SET ingest_run_id=? WHERE ingest_run_id IS NULL", (run,))
        conn.execute("UPDATE sale_listings SET ingest_run_id=? WHERE ingest_run_id IS NULL", (run,))
        set_current_snapshot(conn, "legacy-bootstrap", run)
    for listing in baseline_keys:
        row = conn.execute("SELECT source_kind,address FROM listings WHERE listing_key=? AND ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots)", (listing,)).fetchone()
        if row is None or row[0] != "ulucks" or normal(config["address_contains"]) not in normal(row[1] or ""):
            raise CollectionError("baseline_ownership_not_verified")
        other = conn.execute("SELECT scope_key FROM cloud_baseline_ownership WHERE listing_key=?", (listing,)).fetchone()
        if other and other[0] != key:
            raise CollectionError("baseline_already_owned_by_another_scope")
        conn.execute("INSERT INTO cloud_baseline_ownership(listing_key,scope_key) VALUES (?,?)", (listing, key))
    conn.execute("INSERT INTO cloud_scope_bindings VALUES (?,?,?)", (key, identity, baseline))


def unit_room(value, *, explicit_labels=False):
    # Do not infer room identities from rents/areas/names or strip leading zeroes.
    if explicit_labels:
        from tatemono_map.cloud.partial import literal_room
        result=literal_room(value)
        if result is None:raise CollectionError('legacy_unit_identity_ambiguous')
        return result
    value = normal(value or "").replace(" ", "").upper()
    if value.endswith("号室"):
        value = value[:-2]
    valid = bool(re.fullmatch(r"(?:[1-9][0-9]*|[A-Za-z]+[1-9][0-9]*|[1-9][0-9]*[A-Za-z]+)", value))
    if explicit_labels:
        # Source-declared letter/hyphen labels are compared literally. Never
        # strip a hyphen, remove a block suffix, or coerce a leading zero.
        valid = valid or bool(re.fullmatch(r'(?:[A-Z]+(?:棟)?|(?:[A-Z]+|[1-9][0-9]*)-(?:[A-Z]+|[1-9][0-9]*))',value))
    if not valid:
        raise CollectionError("legacy_unit_identity_ambiguous")
    return value


def prepare_unit_overlaps(conn, key, run, diagnostic=None, *, allow_managed=False):
    """Aggregation equivalence, never company ownership or historical deletion."""
    aliases = dict(conn.execute("SELECT alias_key,canonical_key FROM building_key_aliases"))
    def canonical(value):
        seen = set()
        while value in aliases and aliases[value] != value:
            if value in seen:
                raise CollectionError("alias_cycle")
            seen.add(value)
            value = aliases[value]
        return value
    fresh = conn.execute("SELECT building_key,room_label FROM listings WHERE ingest_run_id=?", (run,)).fetchall()
    units = {(canonical(b), unit_room(room, explicit_labels=allow_managed)) for b, room in fresh}
    if len(units) != len(fresh):
        raise CollectionError("duplicate_canonical_pdf_units")
    touched = {b for b, _ in units}
    old = conn.execute("""SELECT l.listing_key,l.building_key,l.room_label,r.source
        FROM listings l LEFT JOIN ingest_runs r ON r.id=l.ingest_run_id
        WHERE l.source_kind='ulucks' AND l.ingest_run_id<>?
        AND (l.ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots)
          OR EXISTS (SELECT 1 FROM cloud_retained_listings h JOIN current_ingest_snapshots s
            ON s.source=h.scope_key AND s.ingest_run_id=h.ingest_run_id WHERE h.listing_key=l.listing_key))
        AND NOT EXISTS (SELECT 1 FROM cloud_baseline_ownership o WHERE o.listing_key=l.listing_key)
        """, (run,)).fetchall()
    matches = []
    ambiguous = []
    for listing, building, room, source in old:
        building = canonical(building)
        if building not in touched:
            continue
        # Missing legacy room cannot be assumed different from a new unit.
        try:
            identity = (building, unit_room(room, explicit_labels=allow_managed))
        except CollectionError:
            ambiguous.append({'listing_key': listing, 'canonical_building': building, 'room_label': room})
            continue
        if identity in units:
            if source and source.startswith("ulucks:") and not allow_managed:
                raise CollectionError("overlap_with_another_managed_scope")
            matches.append(listing)
    if ambiguous:
        if diagnostic is not None:
            diagnostic.write_text(json.dumps({'code': 'legacy_unit_identity_ambiguous', 'scope_key': key, 'ambiguous_touched_rows': ambiguous}, ensure_ascii=False, indent=2))
            diagnostic.chmod(0o600)
        raise CollectionError('legacy_unit_identity_ambiguous')
    for listing in matches:
        conn.execute("INSERT INTO cloud_unit_overlaps VALUES (?,?,?)", (listing, key, run))
    return len(matches)


def preservation_state(conn, limits=None):
    # Keep every pre-existing historical row byte-for-byte. Hashes stay private.
    tables = ("listings", "sale_listings", "raw_sources", "building_sources", "building_key_aliases", "source_priority")
    if limits is None:
        limits = {t: conn.execute(f'SELECT COALESCE(MAX(rowid),0) FROM "{t}"').fetchone()[0] for t in tables}
    state = {}
    for table, limit in limits.items():
        h = hashlib.sha256()
        for row in conn.execute(f'SELECT * FROM "{table}" WHERE rowid<=? ORDER BY rowid', (limit,)):
            h.update(json.dumps(tuple(row), ensure_ascii=False, default=str).encode())
            h.update(b"\n")
        state[table] = h.hexdigest()
    return limits, state


def update_master(master: Path, pdfs: list[Path], expected_rows: int, config: dict, work: Path, run_id: str, *, confirmed_zero: bool = False, public_baseline: Path | None = None) -> dict:
    validate_master(master)
    if config.get('area_id') == 'kitakyushu' and public_baseline is None:
        raise CollectionError('wide_collection_publication_baseline_required')
    empty = expected_rows == 0 and confirmed_zero and not pdfs
    if not empty and (not pdfs or expected_rows <= 0):
        raise CollectionError("no_confirmed_pdf_rows")
    frames = []
    wide = config.get('area_id') == 'kitakyushu'
    for pdf in pdfs:
        parsed = UlucksParser().parse(pdf)
        if (not wide and qc_check(parsed.df, "ulucks")) or parsed.warnings:
            raise CollectionError("ulucks_parser_qc_failed")
        frames.append(parsed.df)
        # pdfplumber page caches can form cycles. Release them between company
        # PDFs while the single authenticated browser session remains open.
        import gc
        gc.collect()
    from tatemono_map.cli.pdf_batch_run import FINAL_SCHEMA
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FINAL_SCHEMA)
    frame.to_json(work/'parsed-rows.private.json',orient='records',force_ascii=False)
    if len(frame) != expected_rows:
        raise CollectionError("pdf_rows_do_not_match_result_count")
    if not frame["category"].eq("ulucks").all():
        raise CollectionError("unexpected_source_in_pdf")
    from tatemono_map.cloud.wide import area_of
    in_scope = (lambda value: area_of(str(value)) is not None) if config.get('area_id') == 'kitakyushu' else (lambda value: normal(config['address_contains']) in normal(str(value)))
    invalid_scope=~frame['address'].map(in_scope).astype(bool)
    if invalid_scope.any() and (not wide or invalid_scope.all() or (invalid_scope.sum()>=3 and invalid_scope.mean()>0.20)):
        raise CollectionError("pdf_contains_out_of_scope_address")
    # Small, isolated source-address errors are private row anomalies. Retain
    # their prior offers; only trustworthy in-scope rows may enter the master.

    if not wide and frame[["building_name", "address", "room"]].apply(lambda col: col.map(lambda value: not normal(str(value)))).any().any():
        raise CollectionError("pdf_identity_field_missing")
    if not wide and frame.duplicated(["building_name", "address", "room"]).any():
        raise CollectionError("duplicate_pdf_units")
    source_zero = frame.get("area_source_zero", pd.Series(False, index=frame.index)).eq(True)
    invalid_terms=frame['rent_man'].isna() | (frame['rent_man']<=0) | (frame['area_sqm'].isna() & ~source_zero) | (frame['area_sqm']<=0)
    if not wide and invalid_terms.any():
        raise CollectionError("pdf_rent_or_area_invalid")
    print('ULUCKS_COLLECTION_SAFE='+json.dumps({'stage':'parsed','run_id':run_id,'parsed_rows':len(frame)}),flush=True)
    csv_path = work / "master_import.csv"
    key = scope_key(config)
    retired = []
    if config.get('area_id') == 'kitakyushu' and config.get('company_id') == '8':
        retired = [scope_key(dict(config, area_id='kokurakita'))]
    # Export filenames repeat every week/company. Preserve evidence history as
    # well as listing history: source+pdf:ulucks-000.pdf is not a global ID.
    frame["evidence_id"] = frame["evidence_id"].map(lambda value: f"cloud:{key}:{run_id}:{value}")
    anomalies={str(e):'invalid_rent_or_area' for e in frame.loc[invalid_terms,'evidence_id']}
    anomalies.update({str(e):'invalid_scope_address' for e in frame.loc[invalid_scope,'evidence_id']})
    write_master_import_csv(frame, csv_path)
    with connect(master) as conn:
        counts_before = {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('buildings', 'listings', 'sale_listings', 'raw_sources')}
        # SQL concatenation becomes NULL if either attribute is NULL, masking
        # a change to the other attribute. Preserve the two values separately.
        canonical = {row[0]: tuple(row[1:]) for row in conn.execute("SELECT building_id, canonical_name, canonical_address FROM buildings")}
        _prepare_scope(conn, config, key)
        previous = conn.execute("SELECT COUNT(*) FROM listings WHERE ingest_run_id=(SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?)", (key,)).fetchone()[0]
        previous_buildings = {row[0] for row in conn.execute("SELECT DISTINCT building_key FROM listings WHERE ingest_run_id=(SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?)", (key,))}
        for old_scope in retired:
            previous_buildings.update(row[0] for row in conn.execute('SELECT DISTINCT building_key FROM listings WHERE ingest_run_id=(SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?)',(old_scope,)))
        previous_buildings.update(row[0] for row in conn.execute("SELECT DISTINCT l.building_key FROM listings l JOIN cloud_baseline_ownership o ON o.listing_key=l.listing_key WHERE o.scope_key=?", (key,)))
        if previous and not empty and expected_rows < previous * (1 - float(config.get("max_drop_ratio", 0.25))):
            raise CollectionError("scope_row_count_drop_exceeds_limit")
        # Initial company ownership comes from the reviewed private baseline list.
        if not previous and not empty and config["baseline_listing_keys"] and expected_rows < len(config["baseline_listing_keys"]) * (1 - float(config.get("max_drop_ratio", 0.25))):
            raise CollectionError("baseline_row_count_drop_exceeds_limit")
        preserved = preservation_state(conn)
        others = {r[0]: r[1] for r in conn.execute('SELECT source,ingest_run_id FROM current_ingest_snapshots WHERE source<>?', (key,)) if r[0] not in retired}
    report = ingest_master_import_csv(str(master), str(csv_path), source="ulucks", snapshot_source=key, snapshot_key=run_id, auto_seed_high_confidence=bool(config.get("auto_seed_high_confidence", False)), ulucks_full_area=wide, collection_company=config['company_id'], row_anomalies=anomalies)
    if not wide and (report.attached_listings != expected_rows or report.unmatched_count or report.suspect_count):
        raise CollectionError("ingest_unmatched_or_suspect_rows")
    row_counts=report.row_counts or {'accepted_existing':report.attached_listings}
    if sum(row_counts.values()) != expected_rows:
        raise CollectionError('collection_row_accounting_mismatch')
    with connect(master) as conn:
        for building_id, value in canonical.items():
            row = conn.execute("SELECT canonical_name, canonical_address FROM buildings WHERE building_id=?", (building_id,)).fetchone()
            if row is None or tuple(row) != value:
                raise CollectionError("canonical_identity_changed")
        # Bootstrap can assign NULL run IDs once; snapshot after that explicit
        # migration so subsequent ingestion may only append historical records.
        retained=0
        if wide:
            from tatemono_map.cloud.partial import retain_pending
            retained=retain_pending(conn,key,retired,report.ingest_run_id,work/'review-rows.private.csv')
        set_current_snapshot(conn, key, report.ingest_run_id)
        for previous_scope in retired:
            conn.execute('DELETE FROM current_ingest_snapshots WHERE source=?', (previous_scope,))
        if dict(conn.execute("SELECT source,ingest_run_id FROM current_ingest_snapshots WHERE source<>?", (key,))) != others:
            raise CollectionError("other_source_current_snapshot_changed")
        actual = conn.execute("SELECT COUNT(*) FROM listings WHERE ingest_run_id=?", (report.ingest_run_id,)).fetchone()[0]
        if actual != row_counts.get('accepted_existing',0)+row_counts.get('accepted_new',0):
            raise CollectionError("ingested_row_count_mismatch")
        if preservation_state(conn, preserved[0])[1] != preserved[1]:
            raise CollectionError("existing_private_records_changed")
        overlaps = prepare_unit_overlaps(conn, key, report.ingest_run_id, work / 'overlap-review.private.json', allow_managed=config.get('area_id') == 'kitakyushu')
        managed_overlaps=conn.execute("""SELECT COUNT(*) FROM cloud_unit_overlaps o
            JOIN listings l ON l.listing_key=o.listing_key JOIN ingest_runs r ON r.id=l.ingest_run_id
            WHERE o.scope_key=? AND o.ingest_run_id=? AND r.source LIKE 'ulucks:%'""",(key,report.ingest_run_id)).fetchone()[0]
        existing_attached=sum(row[0] in canonical for row in conn.execute('SELECT building_key FROM listings WHERE ingest_run_id=?',(report.ingest_run_id,)))
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise CollectionError("master_foreign_key_error")
    rebuild(str(master))
    validate_master(master)
    counts = export_public(master, work / "public.sqlite3", baseline=public_baseline)
    from tatemono_map.cloud.public_db import rendered_ids
    public_ids = rendered_ids(master)
    with readonly(master) as conn:
        counts_after = {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in counts_before}
        affected = previous_buildings | {row[0] for row in conn.execute("SELECT DISTINCT building_key FROM listings WHERE ingest_run_id=?", (report.ingest_run_id,))}
        if public_ids is not None:
            affected &= public_ids
            if not affected and public_ids:
                affected={min(public_ids)}
        proof = []
        for building in sorted(affected):
            fields = ('building_key','vacancy_count','rent_yen_min','rent_yen_max','area_sqm_min','area_sqm_max','layout_types_json')
            row = conn.execute("SELECT " + ','.join(fields) + " FROM building_summaries WHERE building_key=?", (building,)).fetchone()
            if row is None:
                raise CollectionError("affected_building_summary_missing")
            value = dict(zip(fields, row))
            value['layout_types'] = json.loads(value.pop('layout_types_json') or '[]')
            fees = conn.execute('SELECT maint_yen_min,maint_yen_max FROM building_rental_summaries WHERE building_key=?', (building,)).fetchone()
            value.update(zip(('maint_yen_min','maint_yen_max'), fees or (None,None)))
            proof.append(value)
    from tatemono_map.cli.pdf_batch_run import page_count_fast, sha256_file
    return {"scope_key": key, "integration_contract":"ulucks-partial-v1", "row_counts": row_counts, "held_rows": row_counts.get("held",0), "anomaly_rows": row_counts.get("anomaly",0), "duplicate_rows": row_counts.get("duplicate",0), "retained_rows":retained, "legacy_overlap_rows": overlaps, "managed_overlap_rows": managed_overlaps, "matched_existing_rows": existing_attached, "new_buildings": counts_after["buildings"]-counts_before["buildings"], "area_counts": {str(k): int(v) for k,v in frame["address"].map(area_of).value_counts().items()} if config.get("area_id")=="kitakyushu" else {}, "historical_rows_preserved": True, "acquisition_status": "confirmed_zero" if empty else "pdf_verified", "pdf_count": len(pdfs), "pdfs": [{"pages": page_count_fast(p), "sha256": sha256_file(p)} for p in pdfs], "processed_at": datetime.now(timezone.utc).isoformat(), "counts_before": counts_before, "counts_after": counts_after, "parsed_rows": len(frame), "attached_rows": actual, "ingest_run_id": report.ingest_run_id, "public_counts": counts, "proof": proof}
