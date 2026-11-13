#!/usr/bin/env python3
"""Read-only source -> canonical master -> public DB -> production Web audit."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

from tatemono_map.cloud.fetch_public import fetch as fetch_public_release
from tatemono_map.cloud.public_db import rendered_ids, validate_public
from tatemono_map.cloud.storage import GCSStore, collection_run_id, validate_head
from tatemono_map.cloud.verify_public import verify_site
from tatemono_map.normalize.effective_rentals import canonical_key, effective_rentals
from tatemono_map.normalize.building_summaries import _filter_latest_valid_sale_items
from tatemono_map.util.text import normalize_text


def read_json_blob(store: GCSStore, name: str):
    blob = store.bucket.blob(name)
    try:
        blob.reload()
    except Exception as exc:
        if getattr(exc, "code", None) == 404:
            return None
        raise
    return json.loads(blob.download_as_bytes(if_generation_match=int(blob.generation)))


def num_equal(left, right):
    if left is None or right is None:
        return left is None and right is None
    try:
        return abs(float(left) - float(right)) < 1e-7
    except (TypeError, ValueError):
        return left == right


def source_current_stats(conn, provider: str, source_kind: str):
    row = conn.execute(
        """SELECT COUNT(DISTINCT l.listing_key), COUNT(DISTINCT l.building_key), COUNT(DISTINCT s.source)
           FROM listings l
           JOIN current_ingest_snapshots s ON s.ingest_run_id=l.ingest_run_id
           JOIN ingest_runs i ON i.id=l.ingest_run_id
           WHERE i.source=? AND l.source_kind=?""",
        (provider, source_kind),
    ).fetchone()
    return {"current_snapshot_rows": int(row[0] or 0),
            "current_snapshot_buildings": int(row[1] or 0),
            "current_snapshot_scopes_with_rows": int(row[2] or 0)}


def current_scope_rows(conn, provider: str):
    return conn.execute(
        """SELECT s.source AS scope_key, s.ingest_run_id, i.snapshot_key, i.started_at, i.finished_at
           FROM current_ingest_snapshots s
           JOIN ingest_runs i ON i.id=s.ingest_run_id
           WHERE i.source=? ORDER BY i.started_at""",
        (provider,),
    ).fetchall()


def source_run_summary(store, provider: str, scopes, conn):
    result = {"current_scope_count": len(scopes)}
    if scopes:
        result["latest_snapshot_finished_at"] = max((r[4] or r[3] or "") for r in scopes)
    if provider == "ulucks":
        run_ids = sorted({
            match.group(1)
            for row in scopes
            if (match := re.match(r"^(\d{8}T\d{6}Z-[0-9a-f]{12})-company-\d+$", str(row[2] or "")))
        })
        result["current_acquisition_run_ids"] = run_ids[-5:]
        if os.environ.get("TATEMONO_AUDIT_TARGET_THURSDAY"):
            result["latest_scheduled_acquisition_cycle"] = "weekly-" + os.environ["TATEMONO_AUDIT_TARGET_THURSDAY"]
        if os.environ.get("TATEMONO_AUDIT_ULUCKS_EXECUTION_ID"):
            result["latest_cloud_run_execution_id"] = os.environ["TATEMONO_AUDIT_ULUCKS_EXECUTION_ID"]
        if run_ids:
            batch = read_json_blob(store, f"private-runs/{run_ids[-1]}/batch-result.json")
            if batch:
                result["latest_batch_result"] = {
                    k: batch.get(k) for k in ("run_id", "company_count", "company_census") if k in batch
                }
                completed = batch.get("completed") or []
                result["latest_batch_completed_companies"] = len(completed)
                result["latest_batch_parsed_rows"] = sum(int(x.get("parsed_rows") or 0) for x in completed if isinstance(x, dict))
                result["latest_batch_failed_companies"] = len(batch.get("failed") or [])
                result["latest_batch_unavailable_companies"] = len(batch.get("unavailable") or [])
    elif provider == "realpro":
        target = os.environ.get("TATEMONO_AUDIT_TARGET_THURSDAY")
        if target:
            result["latest_scheduled_acquisition_cycle"] = "weekly-" + target
        execution = os.environ.get("TATEMONO_AUDIT_REALPRO_EXECUTION_ID")
        if execution:
            result["latest_cloud_run_execution_id"] = execution
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='realpro_company_batches'").fetchone():
            batch = conn.execute("SELECT COUNT(DISTINCT scope_key),MAX(acquired_at) FROM realpro_company_batches").fetchone()
            result["stored_company_batch_scopes"] = int(batch[0] or 0)
            result["latest_semantic_batch_acquired_at"] = batch[1]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='realpro_pdf_inputs'").fetchone():
            pdfs = conn.execute("SELECT COUNT(*),COUNT(DISTINCT company),MAX(acquired_at) FROM realpro_pdf_inputs").fetchone()
            result["stored_pdf_inputs"] = int(pdfs[0] or 0)
            result["stored_pdf_companies"] = int(pdfs[1] or 0)
            result["latest_pdf_input_acquired_at"] = pdfs[2]
    elif provider == "mansion_review":
        if os.environ.get("TATEMONO_AUDIT_MANSION_EXECUTION_ID"):
            result["latest_cloud_run_execution_id"] = os.environ["TATEMONO_AUDIT_MANSION_EXECUTION_ID"]
    return result


def compare_rental_source(rows, public_db, public_ids, rendered, web_by_id):
    by_building = defaultdict(list)
    for row in rows:
        if row.get("building_key"):
            by_building[str(row["building_key"])].append(row)

    hidden = set()
    checked = 0
    db_mismatches = 0
    web_mismatches = 0
    missing_db = 0
    missing_web = 0
    has_rental_summary = public_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='building_rental_summaries'"
    ).fetchone()
    for building_id, items in by_building.items():
        if building_id not in public_ids or building_id not in rendered:
            hidden.add(building_id)
            continue
        checked += 1
        summary = public_db.execute(
            "SELECT vacancy_count,rent_yen_min,rent_yen_max,area_sqm_min,area_sqm_max,layout_types_json "
            "FROM building_summaries WHERE building_key=?", (building_id,)
        ).fetchone()
        rental = public_db.execute(
            "SELECT maint_yen_min,maint_yen_max FROM building_rental_summaries WHERE building_key=?", (building_id,)
        ).fetchone() if has_rental_summary else None
        rents = [r.get("rent_yen") for r in items if r.get("rent_yen") is not None]
        areas = [r.get("area_sqm") for r in items if r.get("area_sqm") is not None]
        maints = [r.get("maint_yen") for r in items if r.get("maint_yen") is not None]
        layouts = sorted({normalize_text(r.get("layout")) for r in items if normalize_text(r.get("layout"))})
        expected = {
            "vacancy_count": len(items),
            "rent_yen_min": min(rents) if rents else None,
            "rent_yen_max": max(rents) if rents else None,
            "area_sqm_min": min(areas) if areas else None,
            "area_sqm_max": max(areas) if areas else None,
            "layout_types": layouts,
            "maint_yen_min": min(maints) if maints else None,
            "maint_yen_max": max(maints) if maints else None,
        }
        if summary is None:
            missing_db += 1
            db_mismatches += 1
        else:
            actual = dict(zip(("vacancy_count", "rent_yen_min", "rent_yen_max", "area_sqm_min", "area_sqm_max", "layout_types_json"), summary))
            actual_layouts = json.loads(actual.pop("layout_types_json") or "[]")
            actual["layout_types"] = actual_layouts
            actual.update(dict(zip(("maint_yen_min", "maint_yen_max"), rental or (None, None))))
            if any(not num_equal(actual.get(k), expected.get(k)) for k in (
                "vacancy_count", "rent_yen_min", "rent_yen_max", "area_sqm_min", "area_sqm_max", "maint_yen_min", "maint_yen_max"
            )) or sorted(actual.get("layout_types") or []) != expected["layout_types"]:
                db_mismatches += 1

        web = web_by_id.get(building_id)
        if web is None:
            missing_web += 1
            web_mismatches += 1
        elif any(not num_equal(web.get(web_key), expected.get(db_key)) for web_key, db_key in (
            ("vacancy_count", "vacancy_count"), ("rent_min", "rent_yen_min"), ("rent_max", "rent_yen_max"),
            ("area_min", "area_sqm_min"), ("area_max", "area_sqm_max"), ("maint_min", "maint_yen_min"), ("maint_max", "maint_yen_max")
        )) or sorted(web.get("room_types") or []) != expected["layout_types"]:
            web_mismatches += 1

    return {
        "effective_rows_selected_for_publication": len(rows),
        "effective_buildings_selected_for_publication": len(by_building),
        "visible_buildings_checked": checked,
        "intentionally_not_rendered_or_hidden_buildings": len(hidden),
        "public_db_missing_buildings": missing_db,
        "public_db_summary_mismatches": db_mismatches,
        "web_json_missing_buildings": missing_web,
        "web_json_summary_mismatches": web_mismatches,
        "public_db_and_web_match": db_mismatches == 0 and web_mismatches == 0,
    }


def audit():
    bucket = os.environ.get("TATEMONO_BUCKET") or "tatemono-map-poc-523194690131"
    store = GCSStore(bucket)
    head0, generation0 = store.read_head()
    validate_head(head0)

    with tempfile.TemporaryDirectory(prefix="tatemono-readonly-audit-") as temp:
        root = Path(temp)
        master_path = root / "master.sqlite3"
        public_path = root / "public.sqlite3"
        marker_path = root / "cloud_release.json"

        # fetch_public downloads the exact generation referenced by HEAD and validates its SHA/counts.
        marker = fetch_public_release(store, public_path, marker_path)
        head, generation = store.read_head()
        validate_head(head)
        if generation != generation0 or head["run_id"] != head0["run_id"]:
            raise RuntimeError("head_changed_during_read_only_audit")
        store.download(head["master"], master_path)

        with sqlite3.connect(f"file:{master_path.resolve()}?mode=ro", uri=True) as master, sqlite3.connect(f"file:{public_path.resolve()}?mode=ro", uri=True) as public:
            master.row_factory = sqlite3.Row
            public.row_factory = sqlite3.Row
            master_integrity = master.execute("PRAGMA integrity_check").fetchone()[0]
            public_integrity = public.execute("PRAGMA integrity_check").fetchone()[0]
            if master_integrity != "ok" or public_integrity != "ok":
                raise RuntimeError("sqlite_integrity_check_failed")
            public_counts = validate_public(public_path)
            if public_counts != head.get("report", {}).get("public_counts"):
                raise RuntimeError("public_counts_do_not_match_head")

            scope_rows = {
                provider: current_scope_rows(master, provider)
                for provider in ("ulucks", "realpro", "mansion_review")
            }
            source_runs = {
                "Ulucks": source_run_summary(store, "ulucks", scope_rows["ulucks"], master),
                "RealPro": source_run_summary(store, "realpro", scope_rows["realpro"], master),
                "Mansion Review": source_run_summary(store, "mansion_review", scope_rows["mansion_review"], master),
            }
            mr_cycles = master.execute(
                """SELECT m.cycle,m.kind,COUNT(*) FROM mansion_review_scopes m
                   JOIN current_ingest_snapshots s ON s.source=m.scope_key AND s.ingest_run_id=m.ingest_run_id
                   GROUP BY m.cycle,m.kind ORDER BY m.cycle,m.kind"""
            ).fetchall() if master.execute("SELECT 1 FROM sqlite_master WHERE name='mansion_review_scopes'").fetchone() else []
            source_runs["Mansion Review"]["current_scope_cycles"] = [
                {"cycle": r[0], "kind": r[1], "current_scopes": int(r[2])} for r in mr_cycles
            ]
            if mr_cycles:
                source_runs["Mansion Review"]["latest_cycle"] = max(str(r[0]) for r in mr_cycles)
            head_report = head.get("report", {})
            if head_report.get("integration_contract") == "mansion-review-partial-v1":
                source_runs["Mansion Review"]["latest_integrated_cycle"] = head_report.get("mansion_cycle")
                source_runs["Mansion Review"]["latest_integration"] = {
                    k: head_report.get(k) for k in (
                        "parsed_rows", "attached_rows", "row_counts", "successful_scopes", "absent_scopes", "failed_scopes"
                    ) if k in head_report
                }

            priorities = {r[0]: int(r[1]) for r in master.execute(
                "SELECT source,priority_rank FROM source_priority WHERE domain='rental' AND enabled=1"
            )}
            effective = effective_rentals(master)
            effective_by_kind = defaultdict(list)
            for row in effective:
                effective_by_kind[str(row.get("source_kind") or "")].append(row)

            public_ids = {str(r[0]) for r in public.execute("SELECT building_key FROM building_summaries")}
            rendered = {str(x) for x in rendered_ids(public_path)}
            web_rows = verify_site(marker)
            web_by_id = {str(row["id"]): row for row in web_rows}

            source_specs = [
                ("Ulucks", "ulucks", "ulucks"),
                ("RealPro", "realpro", "realpro"),
                ("Mansion Review", "mansion_review", "mansion_review_chintai"),
            ]
            rental_results = {}
            for label, provider, source_kind in source_specs:
                current = source_current_stats(master, provider, source_kind)
                selected = effective_by_kind[source_kind]
                checks = compare_rental_source(selected, public, public_ids, rendered, web_by_id)
                current_run_ids = {int(r[1]) for r in scope_rows[provider]}
                effective_current = [r for r in selected if r.get("ingest_run_id") in current_run_ids]
                priority = priorities.get(source_kind)
                source_runs[label].update(current)
                source_runs[label]["rental_source_priority_rank"] = priority
                source_runs[label].update(checks)
                source_runs[label]["effective_current_snapshot_rows_selected"] = len(effective_current)
                source_runs[label]["effective_retained_rows_selected"] = len(selected) - len(effective_current)
                source_runs[label]["current_snapshot_rows_not_selected_for_publication"] = max(
                    0, current["current_snapshot_rows"] - len(effective_current)
                )
                rental_results[label] = source_runs[label]

            # Mansion Review sale data has its own current-scope ownership ledger and is not subject to rental priority.
            mr_sale_buildings = set()
            if master.execute("SELECT 1 FROM sqlite_master WHERE name='mansion_review_sale_buildings'").fetchone():
                mr_sale_buildings = {str(r[0]) for r in master.execute(
                    """SELECT DISTINCT b.building_id FROM mansion_review_sale_buildings b
                       JOIN current_ingest_snapshots s ON s.source=b.scope_key"""
                )}
            alias_map = dict(master.execute("SELECT alias_key,canonical_key FROM building_key_aliases")) if master.execute(
                "SELECT 1 FROM sqlite_master WHERE name='building_key_aliases'"
            ).fetchone() else {}
            mr_sale_buildings = {canonical_key(bid, alias_map) for bid in mr_sale_buildings}
            sale_current = master.execute(
                """SELECT COUNT(DISTINCT sl.sale_listing_key),COUNT(DISTINCT sl.building_key)
                   FROM sale_listings sl
                   JOIN current_ingest_snapshots s ON s.ingest_run_id=sl.ingest_run_id
                   JOIN ingest_runs i ON i.id=sl.ingest_run_id
                   WHERE i.source='mansion_review' AND sl.source='mansion_review_mansion'"""
            ).fetchone()
            sale_db_mismatches = sale_web_mismatches = sale_missing_db = sale_missing_web = 0
            sale_checked = 0
            sale_hidden = 0
            sale_expected_rows = 0
            sale_query = """SELECT building_key,price_yen,management_fee_yen,repair_fund_yen,
                tsubo_unit_price_yen AS sqm_unit_price_yen,area_sqm,layout,floor_text,direction_text,
                updated_at,source,ingest_run_id FROM sale_listings"""
            if master.execute("SELECT 1 FROM sqlite_master WHERE name='mansion_review_sale_ownership'").fetchone():
                sale_query += """ WHERE NOT EXISTS (
                    SELECT 1 FROM mansion_review_sale_ownership o
                    JOIN current_ingest_snapshots s ON s.source=o.scope_key
                    WHERE o.listing_key=sale_listings.sale_listing_key)"""
            sale_by_building = defaultdict(list)
            for sale_row in master.execute(sale_query):
                if sale_row["building_key"]:
                    sale_by_building[canonical_key(str(sale_row["building_key"]), alias_map)].append(dict(sale_row))
            for building_id in mr_sale_buildings:
                if building_id not in public_ids or building_id not in rendered:
                    sale_hidden += 1
                    continue
                sale_checked += 1
                normalized_sales = _filter_latest_valid_sale_items(sale_by_building.get(building_id, []))
                sale_expected_rows += len(normalized_sales)
                sale_prices = [int(x["price_yen"]) for x in normalized_sales if x.get("price_yen") is not None]
                sale_areas = [float(x["area_sqm"]) for x in normalized_sales if x.get("area_sqm") is not None]
                expected_sale = {
                    "sale_listing_count": len(normalized_sales),
                    "sale_price_min": min(sale_prices) if sale_prices else None,
                    "sale_price_max": max(sale_prices) if sale_prices else None,
                    "sale_area_min": min(sale_areas) if sale_areas else None,
                    "sale_area_max": max(sale_areas) if sale_areas else None,
                }
                db_row = public.execute(
                    "SELECT sale_listing_count,sale_price_yen_min,sale_price_yen_max,sale_area_sqm_min,sale_area_sqm_max "
                    "FROM building_summaries WHERE building_key=?", (building_id,)
                ).fetchone()
                web = web_by_id.get(building_id)
                if db_row is None or int(db_row[0] or 0) != expected_sale["sale_listing_count"]:
                    sale_missing_db += int(db_row is None)
                    sale_db_mismatches += 1
                elif any(not num_equal(db_row[i], expected_sale[k]) for i, k in (
                    (0, "sale_listing_count"), (1, "sale_price_min"), (2, "sale_price_max"),
                    (3, "sale_area_min"), (4, "sale_area_max")
                )):
                    sale_db_mismatches += 1
                if web is None:
                    sale_missing_web += 1
                    sale_web_mismatches += 1
                elif any(not num_equal(web.get(k), v) for k, v in expected_sale.items()):
                    sale_web_mismatches += 1

            mr_sale = {
                "current_sale_rows": int(sale_current[0] or 0),
                "current_sale_buildings_from_ownership_ledger": len(mr_sale_buildings),
                "expected_sale_rows_after_publication_selection": sale_expected_rows,
                "visible_sale_buildings_checked": sale_checked,
                "intentionally_not_rendered_or_hidden_sale_buildings": sale_hidden,
                "public_db_missing_sale_summaries": sale_missing_db,
                "public_db_sale_summary_mismatches": sale_db_mismatches,
                "web_json_missing_sale_buildings": sale_missing_web,
                "web_json_sale_summary_mismatches": sale_web_mismatches,
                "public_db_and_web_sale_match": sale_db_mismatches == 0 and sale_web_mismatches == 0,
            }

        overall = "success" if all(
            rental_results[label]["public_db_and_web_match"] for label in rental_results
        ) and mr_sale["public_db_and_web_sale_match"] else "attention_required"

        report = {
            "schema": 1,
            "mode": "read_only",
            "project": "tatemono-map",
            "bucket": bucket,
            "head_run_id": head["run_id"],
            "head_generation": generation,
            "collection_run_id": collection_run_id(head),
            "head_integration_contract": head.get("report", {}).get("integration_contract"),
            "scheduled_audit_thursday_jst": os.environ.get("TATEMONO_AUDIT_TARGET_THURSDAY"),
            "master_sha256": head["master"]["sha256"],
            "public_sha256": head["public"]["sha256"],
            "master_integrity": master_integrity,
            "public_integrity": public_integrity,
            "public_counts": public_counts,
            "production_web": {
                "status": "verified",
                "release_run_id": marker["run_id"],
                "public_sha256": marker["public_sha256"],
                "web_building_count": len(web_rows),
                "detail_pages_verified": min(3, len(marker.get("proof") or [])),
            },
            "sources": rental_results,
            "mansion_review_sale": mr_sale,
            "overall": overall,
        }
        print("TATEMONO_SOURCE_PUBLICATION_AUDIT_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
        return report


if __name__ == "__main__":
    try:
        audit()
    except Exception as exc:
        print("TATEMONO_SOURCE_PUBLICATION_AUDIT_JSON=" + json.dumps({
            "schema": 1, "mode": "read_only", "overall": "unconfirmed",
            "error_class": type(exc).__name__,
            "error_code": str(exc)[:120] if str(exc) else type(exc).__name__,
        }, ensure_ascii=False), flush=True)
        raise
