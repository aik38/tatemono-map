param(
  [string]$RepoPath = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path $RepoPath).Path
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
$PY = if (Test-Path $venvPython) { $venvPython } else { "python" }
$env:PYTHONPATH = Join-Path $repo "src"

$dbMain = Join-Path $repo "data\tatemono_map.sqlite3"
$dbPublic = Join-Path $repo "data\public\public.sqlite3"
$aliasCsv = Join-Path $repo "tmp\manual\inputs\building_key_aliases.csv"
$masterCsv = Join-Path $repo "tmp\manual\inputs\buildings_master.csv"

& $PY -m tatemono_map.normalize.building_summaries `
  --db-path $dbMain `
  --alias-csv $aliasCsv `
  --buildings-master-csv $masterCsv
if ($LASTEXITCODE -ne 0) { throw "normalize.building_summaries failed" }

$env:TATEMONO_MAIN_DB = $dbMain
$env:TATEMONO_PUBLIC_DB = $dbPublic

& $PY - <<'PY'
import os
import sqlite3
from pathlib import Path

main_db = Path(os.environ["TATEMONO_MAIN_DB"])
public_db = Path(os.environ["TATEMONO_PUBLIC_DB"])

if not main_db.exists():
    raise SystemExit(f"missing source db: {main_db}")
public_db.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(main_db) as src:
    table = src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='building_summaries'"
    ).fetchone()
    if table is None:
        raise SystemExit("building_summaries missing in source db")

with sqlite3.connect(public_db) as conn:
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("ATTACH DATABASE ? AS src", (str(main_db),))
    create_sql = conn.execute(
        "SELECT sql FROM src.sqlite_master WHERE type='table' AND name='building_summaries'"
    ).fetchone()
    if create_sql is None or not create_sql[0]:
        raise SystemExit("failed to read building_summaries schema from source db")

    conn.execute("DROP TABLE IF EXISTS main.building_summaries")
    import re
    create_main_sql = re.sub(r"^CREATE TABLE(?: IF NOT EXISTS)?\s+building_summaries", "CREATE TABLE main.building_summaries", create_sql[0], count=1)
    conn.execute(create_main_sql)
    conn.execute("INSERT INTO main.building_summaries SELECT * FROM src.building_summaries")
    conn.execute("DETACH DATABASE src")
    conn.commit()

with sqlite3.connect(public_db) as conn:
    listings = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='listings'").fetchone() else 0
    distinct_keys = conn.execute("SELECT COUNT(DISTINCT building_key) FROM listings").fetchone()[0] if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='listings'").fetchone() else 0
    summaries = conn.execute("SELECT COUNT(*) FROM building_summaries").fetchone()[0]

print(f"listings={listings}")
print(f"distinct_building_key={distinct_keys}")
print(f"building_summaries={summaries}")
PY
if ($LASTEXITCODE -ne 0) { throw "public.sqlite3 copy failed" }
