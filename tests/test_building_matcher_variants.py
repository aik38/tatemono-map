from pathlib import Path
from tatemono_map.building_registry.ingest_building_facts import ingest_building_facts_csv
from tatemono_map.building_registry.matcher import match_building
from tatemono_map.building_registry.seed_from_ui import seed_from_ui_csv
from tatemono_map.db.repo import connect


def _seed(db_path: Path, rows: str) -> None:
    seed_csv = db_path.parent / "seed.csv"
    seed_csv.write_text(
        "building_name,address,evidence_url_or_id,merge_to_evidence\n" + rows,
        encoding="utf-8",
    )
    seed_from_ui_csv(str(db_path), str(seed_csv))


def test_matcher_address_variants_comma_range_and_fused(tmp_path: Path) -> None:
    db_path = tmp_path / "matcher_variants.sqlite3"
    _seed(
        db_path,
        "テストマンション,福岡県北九州市小倉北区紺屋町8-3,ui:a,\n"
        "範囲マンション,福岡県北九州市小倉北区紺屋町22-23,ui:b,\n",
    )

    conn = connect(str(db_path))
    comma_match = match_building(conn, "テストマンション", "北九州市小倉北区紺屋町8-3、49号")
    range_match = match_building(conn, "範囲マンション", "北九州市小倉北区紺屋町22-23〜24")
    fused_match = match_building(conn, "テストマンション", "北九州市小倉北区紺屋町83番")
    conn.close()

    assert comma_match.building_id is not None
    assert range_match.building_id is not None
    assert fused_match.building_id is not None


def test_variant_match_registers_alias_for_future_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    _seed(db_path, "テストマンション,福岡県北九州市小倉北区紺屋町8-3,ui:a,\n")

    csv_path = tmp_path / "facts.csv"
    csv_path.write_text(
        "building_name,address,evidence_id,property_kind\n"
        "テストマンション,福岡県北九州市小倉北区紺屋町83番,mr:1,chintai\n",
        encoding="utf-8",
    )
    report = ingest_building_facts_csv(str(db_path), str(csv_path), source="mansion_review_list_facts", create_missing_safe=True)
    assert report.matched == 1

    conn = connect(str(db_path))
    aliases = conn.execute("SELECT COUNT(*) FROM building_key_aliases").fetchone()[0]
    conn.close()
    assert aliases >= 1


def test_safe_create_missing_blocks_close_match_and_vague_address(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    _seed(db_path, "既存マンション,福岡県北九州市小倉北区紺屋町8-3,ui:a,\n")

    csv_path = tmp_path / "facts.csv"
    csv_path.write_text(
        "building_name,address,evidence_id,property_kind\n"
        "既存マンション,福岡県北九州市小倉北区紺屋町83番,mr:close,chintai\n"
        "曖昧マンション,福岡県北九州市小倉北区老松町,mr:vague,chintai\n",
        encoding="utf-8",
    )
    report = ingest_building_facts_csv(str(db_path), str(csv_path), source="mansion_review_list_facts", create_missing_safe=True)

    conn = connect(str(db_path))
    buildings = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    conn.close()

    assert report.created == 0
    assert buildings == 1
