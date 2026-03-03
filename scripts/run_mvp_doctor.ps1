param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$DbPath = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path $RepoPath).Path
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
if (-not $DbPath) { $DbPath = Join-Path $repo "data\tatemono_map.sqlite3" }

Push-Location $repo
try {
  & $py - <<'PY' $DbPath
import sqlite3
import sys

db_path = sys.argv[1]
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

queries = {
    "duplicates_norm": """
        SELECT norm_name, norm_address, COUNT(*) AS c
        FROM buildings
        GROUP BY norm_name, norm_address
        HAVING COUNT(*) > 1
        ORDER BY c DESC
    """,
    "duplicates_canonical_address": """
        SELECT canonical_address, COUNT(*) AS c
        FROM buildings
        WHERE canonical_address IS NOT NULL AND canonical_address <> ''
        GROUP BY canonical_address
        HAVING COUNT(*) > 1
        ORDER BY c DESC
    """,
    "orphans": """
        SELECT l.listing_key, l.building_key
        FROM listings l
        LEFT JOIN buildings b ON b.building_id = l.building_key
        WHERE l.building_key IS NOT NULL AND l.building_key <> '' AND b.building_id IS NULL
    """,
}

for label, sql in queries.items():
    rows = conn.execute(sql).fetchall()
    print(f"{label}={len(rows)}")

buildings_count = conn.execute("SELECT COUNT(*) AS c FROM buildings").fetchone()["c"]
summaries_count = conn.execute("SELECT COUNT(*) AS c FROM building_summaries").fetchone()["c"]
print(f"buildings_count={buildings_count}")
print(f"building_summaries_count={summaries_count}")

bunjo = conn.execute(
    """
    SELECT
      COUNT(*) AS bunjo_count,
      SUM(CASE WHEN sale_price_yen_avg IS NOT NULL THEN 1 ELSE 0 END) AS with_sale_price_avg,
      SUM(CASE WHEN sale_listing_count IS NOT NULL AND sale_listing_count > 0 THEN 1 ELSE 0 END) AS with_sale_listing_count
    FROM buildings
    WHERE property_kind='bunjo'
    """
).fetchone()
print(f"bunjo_count={bunjo['bunjo_count'] or 0}")
print(f"bunjo_with_sale_price_avg={bunjo['with_sale_price_avg'] or 0}")
print(f"bunjo_with_sale_listing_count={bunjo['with_sale_listing_count'] or 0}")

has_issues = False
if conn.execute(queries['duplicates_norm']).fetchone() is not None:
    has_issues = True
if conn.execute(queries['duplicates_canonical_address']).fetchone() is not None:
    has_issues = True
if conn.execute(queries['orphans']).fetchone() is not None:
    has_issues = True

conn.close()
sys.exit(1 if has_issues else 0)
PY
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
  Pop-Location
}
