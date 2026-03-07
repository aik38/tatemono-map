from __future__ import annotations

import sqlite3

from tatemono_map.cli.apply_building_corrections import CorrectionRow, process_rows


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE buildings(
          building_id TEXT PRIMARY KEY,
          canonical_name TEXT,
          canonical_address TEXT,
          norm_name TEXT,
          norm_address TEXT,
          hidden_from_public INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address) VALUES (?,?,?,?,?)",
        ("b1", "コンフォートプレイス小 倉", "福岡県北九州市小倉北区中原西3-4-3", "コンフォートプレイス小 倉", "福岡県北九州市小倉北区中原西3-4-3"),
    )
    conn.execute(
        "INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address) VALUES (?,?,?,?,?)",
        ("b2", "CITRUS TREE", "北九州市小倉南区足立", "CITRUS TREE", "北九州市小倉南区足立"),
    )
    return conn


def test_process_rows_applies_name_fix() -> None:
    conn = _conn()
    rows = [
        CorrectionRow(
            row_no=2,
            status="pending",
            action="fix",
            target_building_name="コンフォートプレイス小 倉",
            target_address="福岡県北九州市小倉北区中原西3-4-3",
            field="building_name",
            old_value="コンフォートプレイス小 倉",
            new_value="コンフォートプレイス小倉",
            note="",
            source="frontend",
            error_type="building_name_spacing",
        )
    ]

    results, duplicates = process_rows(conn, rows, apply=True, allow_incomplete_address=False)

    assert results[0].outcome == "applied"
    assert results[0].matched_building_id == "b1"
    assert duplicates == []
    new_name = conn.execute("SELECT canonical_name FROM buildings WHERE building_id='b1'").fetchone()[0]
    assert new_name == "コンフォートプレイス小倉"


def test_process_rows_holds_citrus_tree_incomplete_address() -> None:
    conn = _conn()
    rows = [
        CorrectionRow(
            row_no=3,
            status="pending",
            action="fix",
            target_building_name="CITRUS TREE",
            target_address="北九州市小倉南区足立",
            field="address",
            old_value="北九州市小倉南区足立",
            new_value="北九州市小倉北区足立",
            note="区名は要補正・枝番未確認",
            source="frontend",
            error_type="address_incomplete",
        )
    ]

    results, _ = process_rows(conn, rows, apply=True, allow_incomplete_address=False)

    assert results[0].outcome == "held"
    assert results[0].reason == "hold_citrus_tree_incomplete_address"
    old_address = conn.execute("SELECT canonical_address FROM buildings WHERE building_id='b2'").fetchone()[0]
    assert old_address == "北九州市小倉南区足立"


def test_process_rows_marks_drop_duplicate_loser_hidden() -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address) VALUES (?,?,?,?,?)",
        (
            "b3",
            "ニューシティアパートメンツ南小倉II",
            "福岡県北九州市小倉北区東篠崎3",
            "ニューシティアパートメンツ南小倉II",
            "福岡県北九州市小倉北区東篠崎3",
        ),
    )
    rows = [
        CorrectionRow(
            row_no=4,
            status="approved",
            action="drop_duplicate_loser",
            target_building_name="ニューシティアパートメンツ南小倉II",
            target_address="福岡県北九州市小倉北区東篠崎3",
            field="",
            old_value="",
            new_value="",
            note="勝ちレコードあり。公開から除外",
            source="frontend",
            error_type="alias_or_duplicate_candidate",
        )
    ]

    results, duplicates = process_rows(conn, rows, apply=True, allow_incomplete_address=False)

    assert duplicates == []
    assert results[0].outcome == "applied"
    assert results[0].reason == "hidden_from_public"
    hidden = conn.execute("SELECT hidden_from_public FROM buildings WHERE building_id='b3'").fetchone()[0]
    assert hidden == 1
