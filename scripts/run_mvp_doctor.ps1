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
  $code = @'
import csv
import sqlite3
import sys
from pathlib import Path


def latest_data_rows(base: Path, pattern: str) -> tuple[int, Path | None]:
    files = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return 0, None
    latest = files[0]
    with latest.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        return 0, latest
    return max(0, len(rows) - 1), latest


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


db_path = sys.argv[1]
repo = Path(sys.argv[2])
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

buildings_cols = table_columns(conn, "buildings")
listings_cols = table_columns(conn, "listings")

name_col = "normalized_name" if "normalized_name" in buildings_cols else "norm_name"
address_col = "normalized_address" if "normalized_address" in buildings_cols else "norm_address"
has_norm_pair = name_col in buildings_cols and address_col in buildings_cols
has_canonical_address = "canonical_address" in buildings_cols

building_key_col = "building_id" if "building_id" in buildings_cols else None
listing_building_col = "building_key" if "building_key" in listings_cols else None

status_ok = True

print("[doctor] mvp_doctor start")

if not has_norm_pair:
    print(f"[doctor][WARN] normalized duplicate check skipped (columns missing): name_col={name_col} address_col={address_col}")
else:
    duplicates_norm = conn.execute(
        f"""
        SELECT {name_col}, {address_col}, COUNT(*) AS c
        FROM buildings
        WHERE COALESCE({name_col}, '') <> '' AND COALESCE({address_col}, '') <> ''
        GROUP BY {name_col}, {address_col}
        HAVING COUNT(*) > 1
        """
    ).fetchone()
    duplicates_norm_count = 0 if duplicates_norm is None else duplicates_norm["c"]
    print(f"[doctor] duplicates_buildings_normalized={duplicates_norm_count}")
    if duplicates_norm is not None:
        status_ok = False
        print("[doctor][NG] Duplicate buildings found for normalized_name + normalized_address")

if has_canonical_address:
    duplicates_canonical = conn.execute(
        """
        SELECT canonical_address, COUNT(*) AS c
        FROM buildings
        WHERE canonical_address IS NOT NULL AND canonical_address <> ''
        GROUP BY canonical_address
        HAVING COUNT(*) > 1
        """
    ).fetchone()
    duplicates_canonical_count = 0 if duplicates_canonical is None else duplicates_canonical["c"]
    print(f"[doctor] duplicates_buildings_canonical_address={duplicates_canonical_count}")
    if duplicates_canonical is not None:
        status_ok = False
        print("[doctor][NG] Duplicate buildings found for canonical_address")
else:
    print("[doctor][WARN] canonical_address duplicate check skipped (column missing)")

if not building_key_col or not listing_building_col:
    print("[doctor][WARN] orphan listing check skipped (building_id/building_key column missing)")
else:
    orphan_count = conn.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM listings l
        LEFT JOIN buildings b ON b.{building_key_col} = l.{listing_building_col}
        WHERE l.{listing_building_col} IS NOT NULL
          AND l.{listing_building_col} <> ''
          AND b.{building_key_col} IS NULL
        """
    ).fetchone()["c"]
    print(f"[doctor] orphan_listings={orphan_count}")
    if orphan_count > 0:
        status_ok = False
        print("[doctor][NG] Orphan listings found (listings.building_key not present in buildings)")

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

review_dir = repo / "tmp" / "review"
unmatched_listings, unmatched_listings_file = latest_data_rows(review_dir, "unmatched_listings_*.csv")
unmatched_facts, unmatched_facts_file = latest_data_rows(review_dir, "unmatched_building_facts_*.csv")
print(f"[doctor] unmatched_listings_latest_rows={unmatched_listings}")
print(f"[doctor] unmatched_listings_latest_file={unmatched_listings_file or 'missing'}")
print(f"[doctor] unmatched_building_facts_latest_rows={unmatched_facts}")
print(f"[doctor] unmatched_building_facts_latest_file={unmatched_facts_file or 'missing'}")
if unmatched_facts_file is not None and unmatched_facts > 0:
    status_ok = False
    print("[doctor][NG] Latest unmatched_building_facts CSV has unresolved rows; manual review required")

conn.close()
if status_ok:
    print("[doctor] RESULT=OK")
    sys.exit(0)

print("[doctor] RESULT=NG")
sys.exit(1)
'@
  & $py -c $code $DbPath $repo
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
  Pop-Location
}
