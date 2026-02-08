param(
    [string]$DbPath = "data/tatemono_map.sqlite3"
)

$ErrorActionPreference = "Stop"

$dir = Split-Path -Parent $DbPath
if ($dir -and -not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

$full = [System.IO.Path]::GetFullPath($DbPath)
if (-not (Test-Path -LiteralPath $full)) {
    Write-Error "DB file not found: $full"
}

Write-Host "DB_PATH=$full"

python -c @"
import sqlite3
from pathlib import Path

db = Path(r'''$full''')
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
print("TABLES=" + ",".join(tables))
for table in ("raw_sources", "listings", "building_summaries"):
    c = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"COUNT[{table}]={c}")
for row in conn.execute("SELECT source_kind, COUNT(*) FROM raw_sources GROUP BY source_kind ORDER BY source_kind"):
    print(f"BY_KIND[{row[0]}]={row[1]}")
conn.close()
"@
