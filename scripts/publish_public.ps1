param(
  [string]$RepoPath = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path $RepoPath).Path
if (-not (Test-Path (Join-Path $repo ".git"))) {
  throw "Not a git repository: $repo"
}
if (-not (Test-Path (Join-Path $repo "pyproject.toml"))) {
  throw "pyproject.toml not found. Refusing to run outside tatemono-map repo: $repo"
}

$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Python executable not found: $venvPython`nRun scripts/setup.ps1 first."
}

$env:PYTHONPATH = Join-Path $repo "src"

$dbMain = Join-Path $repo "data\tatemono_map.sqlite3"
$dbPublic = Join-Path $repo "data\public\public.sqlite3"
$aliasCsv = Join-Path $repo "tmp\manual\inputs\building_key_aliases.csv"
$masterCsv = Join-Path $repo "tmp\manual\inputs\buildings_master.csv"

& $venvPython -m tatemono_map.normalize.building_summaries `
  --db-path $dbMain `
  --alias-csv $aliasCsv `
  --buildings-master-csv $masterCsv
if ($LASTEXITCODE -ne 0) { throw "normalize.building_summaries failed" }

$pyScript = @'
import os
import re
import sqlite3
import sys
from pathlib import Path

main_db = Path(os.environ["TATEMONO_MAIN_DB"])
public_db = Path(os.environ["TATEMONO_PUBLIC_DB"])
tmp_db = Path(f"{public_db}.tmp")

if not main_db.exists():
    raise SystemExit(f"missing source db: {main_db}")
public_db.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(main_db) as src:
    table = src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='building_summaries'"
    ).fetchone()
    if table is None:
        raise SystemExit("building_summaries missing in source db")

with sqlite3.connect(main_db) as src:
    src.execute("PRAGMA busy_timeout=5000")
    create_sql = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='building_summaries'"
    ).fetchone()
    if create_sql is None or not create_sql[0]:
        raise SystemExit("failed to read building_summaries schema from source db")

if tmp_db.exists():
    tmp_db.unlink()

with sqlite3.connect(tmp_db) as conn:
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA busy_timeout=5000")
    create_main_sql = re.sub(
        r"^CREATE TABLE(?: IF NOT EXISTS)?\\s+building_summaries",
        "CREATE TABLE main.building_summaries",
        create_sql[0],
        count=1,
    )
    conn.execute(create_main_sql)
    conn.execute("ATTACH DATABASE ? AS src", (str(main_db),))
    conn.execute("INSERT INTO main.building_summaries SELECT * FROM src.building_summaries")
    conn.commit()
    conn.execute("DETACH DATABASE src")

try:
    os.replace(tmp_db, public_db)
except OSError as exc:
    if getattr(exc, "winerror", None) == 32:
        print(
            "[ERROR] Failed to replace public.sqlite3 because it is locked. "
            "Close DB Browser / VSCode SQLite extension and rerun scripts/publish_public.ps1.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise

with sqlite3.connect(main_db) as conn:
    listings_count_main = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    summaries_count_main = conn.execute("SELECT COUNT(*) FROM building_summaries").fetchone()[0]

with sqlite3.connect(public_db) as conn:
    conn.execute("PRAGMA busy_timeout=5000")
    summaries_count_public = conn.execute("SELECT COUNT(*) FROM building_summaries").fetchone()[0]
    distinct_keys_public = conn.execute(
        "SELECT COUNT(DISTINCT building_key) FROM building_summaries"
    ).fetchone()[0]

print(f"listings count (main): {listings_count_main}")
print(f"building_summaries count (main): {summaries_count_main}")
print(f"building_summaries count (public): {summaries_count_public}")
print(f"building_summaries distinct building_key (public): {distinct_keys_public}")
'@

$env:TATEMONO_MAIN_DB = $dbMain
$env:TATEMONO_PUBLIC_DB = $dbPublic
$tempPy = Join-Path $env:TEMP ("publish_public_{0}.py" -f ([guid]::NewGuid().ToString("N")))
Set-Content -LiteralPath $tempPy -Value $pyScript -Encoding UTF8
try {
  & $venvPython $tempPy
  if ($LASTEXITCODE -ne 0) { throw "public.sqlite3 copy failed" }
}
finally {
  if (Test-Path -LiteralPath $tempPy) {
    Remove-Item -LiteralPath $tempPy -Force
  }
}
