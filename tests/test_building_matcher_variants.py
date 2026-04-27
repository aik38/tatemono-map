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


def test_matcher_blocks_multi_lot_or_range_and_accepts_fused(tmp_path: Path) -> None:
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

    assert comma_match.building_id is None
    assert comma_match.reason == "address_multi_or_range"
    assert range_match.building_id is None
    assert range_match.reason == "address_multi_or_range"
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


def test_safe_create_missing_blocks_multi_lot_or_range_address(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"

    csv_path = tmp_path / "facts.csv"
    csv_path.write_text(
        "building_name,address,evidence_id,property_kind\n"
        "複数地番マンション,福岡県北九州市小倉北区紺屋町8-3、49号,mr:multi,chintai\n"
        "レンジ地番マンション,福岡県北九州市小倉北区紺屋町22-23〜24,mr:range,chintai\n",
        encoding="utf-8",
    )

    report = ingest_building_facts_csv(str(db_path), str(csv_path), source="mansion_review_list_facts", create_missing_safe=True)

    conn = connect(str(db_path))
    buildings = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    conn.close()

    assert report.created == 0
    assert report.unresolved == 2
    assert report.auto_seed_skipped == 2
    assert buildings == 0


def test_safe_create_missing_creates_once_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "idempotent.sqlite3"
    csv_path = tmp_path / "facts.csv"
    csv_path.write_text(
        "building_name,address,evidence_id,property_kind\n"
        "新規マンション,福岡県北九州市小倉北区馬借1-2-3,mr:new1,chintai\n",
        encoding="utf-8",
    )

    first = ingest_building_facts_csv(str(db_path), str(csv_path), source="mansion_review_list_facts", create_missing_safe=True)
    second = ingest_building_facts_csv(str(db_path), str(csv_path), source="mansion_review_list_facts", create_missing_safe=True)

    conn = connect(str(db_path))
    buildings = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    conn.close()

    assert first.created == 1
    assert first.unresolved == 0
    assert second.created == 0
    assert second.matched == 1
    assert buildings == 1


def test_safe_create_missing_off_keeps_unresolved(tmp_path: Path) -> None:
    db_path = tmp_path / "off.sqlite3"
    csv_path = tmp_path / "facts.csv"
    csv_path.write_text(
        "building_name,address,evidence_id,property_kind\n"
        "未登録マンション,福岡県北九州市小倉北区馬借2-3-4,mr:new2,chintai\n",
        encoding="utf-8",
    )

    report = ingest_building_facts_csv(str(db_path), str(csv_path), source="mansion_review_list_facts", create_missing_safe=False)

    conn = connect(str(db_path))
    buildings = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    conn.close()

    assert report.created == 0
    assert report.unresolved == 1
    assert buildings == 0


def test_safe_create_missing_skips_collision_with_existing_norm_address(tmp_path: Path) -> None:
    db_path = tmp_path / "collision.sqlite3"
    _seed(db_path, "既存建物,福岡県北九州市小倉北区馬借3-4-5,ui:a,\n")

    csv_path = tmp_path / "facts.csv"
    csv_path.write_text(
        "building_name,address,evidence_id,property_kind\n"
        "別名建物,福岡県北九州市小倉北区馬借3-4-5,mr:new3,chintai\n",
        encoding="utf-8",
    )

    report = ingest_building_facts_csv(str(db_path), str(csv_path), source="mansion_review_list_facts", create_missing_safe=True)
    assert report.created == 0
    assert report.auto_seed_skipped == 0
    assert report.matched == 1


def test_matcher_alias_requires_address_match_to_avoid_sibling_mix(tmp_path: Path) -> None:
    db_path = tmp_path / "alias_guard.sqlite3"
    _seed(
        db_path,
        "サンライフ恒見,福岡県北九州市門司区恒見町1-1,ui:a,\n"
        "サンライフ恒見２,福岡県北九州市門司区恒見町2-1,ui:b,\n",
    )

    conn = connect(str(db_path))
    conn.execute(
        """
        INSERT INTO building_sources(source, evidence_id, building_id, raw_name, raw_address, extracted_at)
        VALUES ('mansion_review_list_facts','src:1',(SELECT building_id FROM buildings WHERE canonical_name='サンライフ恒見'),'サンライフ恒見２','福岡県北九州市門司区恒見町1-1',CURRENT_TIMESTAMP)
        """
    )
    conn.commit()

    result = match_building(conn, "さんらいふ恒見2", "北九州市門司区恒見町2-1")
    conn.close()

    assert result.building_id is not None
    assert result.reason != "alias_exact"


def test_matcher_blocks_suffix_conflict_even_when_address_exact(tmp_path: Path) -> None:
    db_path = tmp_path / "suffix_guard.sqlite3"
    _seed(db_path, "ニューシティ南小倉II,福岡県北九州市小倉北区中井1-2,ui:a,\n")

    conn = connect(str(db_path))
    result = match_building(conn, "ニューシティ南小倉III", "北九州市小倉北区中井1-2")
    conn.close()

    assert result.building_id is None
    assert result.reason == "name_suffix_conflict"


def test_ingest_facts_attaches_when_canonical_is_split_only_by_chome_notation(tmp_path: Path) -> None:
    db_path = tmp_path / "split_chome.sqlite3"
    _seed(db_path, "サンレリウス小倉駅南,福岡県北九州市小倉北区鍛冶町2丁目5番8号,ui:a,\n")

    conn = connect(str(db_path))
    conn.execute(
        """
        INSERT INTO buildings(
            building_id, canonical_name, canonical_address, norm_name, norm_address, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            "manual-split",
            "サンレリウス小倉駅南",
            "北九州市小倉北区鍛冶町二丁目5番8号",
            "サンレリウス小倉駅南",
            "北九州市小倉北区鍛冶町2-5-8",
        ),
    )
    conn.commit()
    conn.close()

    csv_path = tmp_path / "facts.csv"
    csv_path.write_text(
        "building_name,address,evidence_id,structure,built_year_month,property_kind\n"
        "サンレリウス小倉駅南,福岡県北九州市小倉北区鍛冶町2丁目5番8号,mansion_review:https://www.mansion-review.jp/mansion/1638299.html,RC,2009-02,bunjo\n",
        encoding="utf-8",
    )
    report = ingest_building_facts_csv(str(db_path), str(csv_path), source="mansion_review_facts", merge="fill_only")
    assert report.matched == 1
    assert report.unresolved == 0

    conn = connect(str(db_path))
    attached = conn.execute(
        """
        SELECT b.canonical_name, b.structure, b.built_year_month, b.property_kind
        FROM building_sources s
        JOIN buildings b ON b.building_id = s.building_id
        WHERE s.source='mansion_review_facts'
          AND s.evidence_id='mansion_review:https://www.mansion-review.jp/mansion/1638299.html'
        """
    ).fetchone()
    conn.close()

    assert attached is not None
    assert attached["canonical_name"] == "サンレリウス小倉駅南"
    assert attached["structure"] == "RC"
    assert attached["built_year_month"] == "2009-02"
    assert attached["property_kind"] == "bunjo"
