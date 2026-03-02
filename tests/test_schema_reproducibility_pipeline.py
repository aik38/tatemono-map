from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tatemono_map.db.schema import ensure_schema
from tests.conftest import repo_path


def test_fresh_db_schema_supports_master_ingest_and_summary_cli(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.sqlite3"
    csv_path = repo_path("tests", "fixtures", "building_master", "master_import_tiny.csv")
    ensure_schema(db_path)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_path("src"))

    subprocess.run(
        [
            sys.executable,
            "-m",
            "tatemono_map.building_registry.ingest_master_import",
            "--db",
            str(db_path),
            "--csv",
            str(csv_path),
            "--source",
            "master_import",
        ],
        check=True,
        env=env,
        cwd=str(repo_path()),
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tatemono_map.normalize.building_summaries",
            "--db-path",
            str(db_path),
        ],
        check=True,
        env=env,
        cwd=str(repo_path()),
    )
