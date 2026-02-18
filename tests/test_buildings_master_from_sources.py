from __future__ import annotations

import csv

from tatemono_map.buildings_master.from_sources import normalize_address_jp, normalize_building_name, run


def _write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_normalize_address_jp_basic():
    assert normalize_address_jp("北九州市小倉北区 1丁目2番3号") == "福岡県北九州市小倉北区1-2-3"
    assert normalize_address_jp("福岡県北九州市小倉北区１丁目２番地３号") == "福岡県北九州市小倉北区1-2-3"


def test_normalize_building_name_room_noise_removed():
    assert normalize_building_name("ＡＢＣマンション 101号室") == "ABCマンション"
    assert normalize_building_name("レジデンス－X 202") == "レジデンス-X"


def test_dedup_and_suspects(tmp_path):
    pdf = tmp_path / "final.csv"
    mr = tmp_path / "mr.csv"
    out = tmp_path / "out"

    _write_csv(
        pdf,
        ["building_name", "address", "source_pdf"],
        [
            {"building_name": "Aマンション 101号室", "address": "北九州市小倉北区1丁目2番3号", "source_pdf": "a.pdf"},
            {"building_name": "Aマンション 102号室", "address": "北九州市小倉北区1丁目2番3号", "source_pdf": "a.pdf"},
            {"building_name": "", "address": "北九州市小倉北区1丁目", "source_pdf": "b.pdf"},
        ],
    )
    _write_csv(
        mr,
        ["building_name", "address", "detail_url"],
        [
            {"building_name": "Aマンション", "address": "福岡県北九州市小倉北区1丁目2番3号", "detail_url": "https://example.com/d/1"},
            {"building_name": "別名マンション", "address": "福岡県北九州市小倉北区1丁目2番3号", "detail_url": "https://example.com/d/2"},
            {"building_name": "Aマンション", "address": "福岡県北九州市小倉北区1丁目2番3号", "detail_url": "https://example.com/d/1"},
        ],
    )

    stats = run(pdf, mr, out)

    assert stats["counts"]["mansion_review_input_rows"] == 3
    assert stats["counts"]["mansion_review_dedup_rows"] == 2

    suspects = _read_csv(out / "buildings_master_suspects.csv")
    reasons = "\n".join(row["reason_codes"] for row in suspects)
    assert "weak_address" in reasons
    assert "name_conflict_same_address" in reasons

    merged = _read_csv(out / "buildings_master_merged_primary_wins.csv")
    assert any("https://example.com/d/1" in row["evidence_url_or_id"] for row in merged)
