import shutil
import csv
import sqlite3
import subprocess
from pathlib import Path


def _write_unmatched_csv(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["building_name", "address"])
        for i in range(rows):
            writer.writerow([f"b{i}", f"addr{i}"])


def test_run_mvp_doctor_warn_for_unmatched_facts(tmp_path: Path) -> None:
    if not shutil.which("pwsh"):
        import pytest

        pytest.skip("pwsh not found")

    db_path = tmp_path / "tatemono_map.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE buildings (
                building_id TEXT PRIMARY KEY,
                canonical_name TEXT,
                canonical_address TEXT,
                norm_name TEXT,
                norm_address TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE listings (
                listing_key TEXT PRIMARY KEY,
                building_key TEXT
            )
            """
        )
        conn.execute("CREATE TABLE building_summaries (building_key TEXT PRIMARY KEY)")
        conn.execute(
            "INSERT INTO buildings(building_id, canonical_name, canonical_address, norm_name, norm_address) VALUES ('b1','A','東京都A','a','tokyo-a')"
        )

    _write_unmatched_csv(tmp_path / "tmp/review/unmatched_building_facts_20990101_000001.csv", rows=2)
    _write_unmatched_csv(tmp_path / "tmp/review/unmatched_listings_20990101_000001.csv", rows=0)

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/run_mvp_doctor.ps1",
            "-RepoPath",
            str(tmp_path),
            "-DbPath",
            str(db_path),
            "-UnmatchedFactsPolicy",
            "warn",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "[doctor] unmatched_building_facts_latest_rows=2" in result.stdout
    assert "[doctor] RESULT=WARN" in result.stdout


def test_merge_duplicate_buildings_noop_on_ambiguous_case(tmp_path: Path) -> None:
    db_path = tmp_path / "tatemono_map.sqlite3"
    review_dir = tmp_path / "tmp/review"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE buildings (
                building_id TEXT PRIMARY KEY,
                canonical_name TEXT,
                canonical_address TEXT,
                norm_name TEXT,
                norm_address TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute("CREATE TABLE listings (listing_key TEXT PRIMARY KEY, building_key TEXT)")
        conn.execute("CREATE TABLE building_summaries (building_key TEXT PRIMARY KEY)")
        conn.execute(
            "INSERT INTO buildings VALUES ('keep1','Aマンション','東京都A','a','tokyo-a','2026-01-01','2026-01-02')"
        )
        conn.execute(
            "INSERT INTO buildings VALUES ('keep2','Aマンション','東京都A','a','tokyo-a','2026-01-03','2026-01-04')"
        )
        conn.execute("INSERT INTO listings VALUES ('l1','keep1')")
        conn.execute("INSERT INTO listings VALUES ('l2','keep2')")

    env = dict(**__import__("os").environ, PYTHONPATH=str(Path("src").resolve()))
    result = subprocess.run(
        [
            "python",
            "-m",
            "tatemono_map.cli.merge_duplicate_buildings",
            "--db",
            str(db_path),
            "--review-dir",
            str(review_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert "RESULT=NOOP_AMBIGUOUS" in result.stdout

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0] == 2
        listing_keys = {row[0] for row in conn.execute("SELECT DISTINCT building_key FROM listings")}
        assert listing_keys == {"keep1", "keep2"}

    candidate_files = list(review_dir.glob("duplicate_candidates_*.csv"))
    merge_files = list(review_dir.glob("duplicate_merge_*.csv"))
    assert candidate_files, "expected duplicate_candidates CSV"
    assert merge_files, "expected duplicate_merge CSV"
