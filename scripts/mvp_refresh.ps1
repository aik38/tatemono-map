param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$CityIds = "1616,1619",
  [string]$Kinds = "mansion,chintai",
  [double]$SleepSec = 0.7,
  [int]$MaxPages = 0,
  [switch]$CreateMissingSafe = $false
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path $RepoPath).Path
if (-not (Test-Path (Join-Path $repo ".git"))) { throw "Not a git repository: $repo" }
if (-not (Test-Path (Join-Path $repo "pyproject.toml"))) { throw "pyproject.toml not found: $repo" }

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = Join-Path $repo (Join-Path "tmp/backup" $timestamp)
$outDir = Join-Path $backupRoot "out"
$doctorStatus = "NG"

function Copy-OptionalItem {
  param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Destination
  )
  if (Test-Path $Source) {
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    Copy-Item -Path $Source -Destination $Destination -Recurse -Force
    Write-Host "[BACKUP] copied: $Source -> $Destination"
  } else {
    Write-Host "[BACKUP] skip missing: $Source"
  }
}

Push-Location $repo
try {
  New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
  New-Item -ItemType Directory -Path $outDir -Force | Out-Null

  $mainDb = Join-Path $repo "data/tatemono_map.sqlite3"
  $publicDb = Join-Path $repo "data/public/public.sqlite3"
  $distDir = Join-Path $repo "dist"

  Copy-OptionalItem -Source $mainDb -Destination (Join-Path $backupRoot "data/tatemono_map.sqlite3")
  Copy-OptionalItem -Source $publicDb -Destination (Join-Path $backupRoot "data/public/public.sqlite3")
  Copy-OptionalItem -Source $distDir -Destination (Join-Path $backupRoot "dist")

  Write-Host "BACKUP=$backupRoot"

  Write-Host "[STEP] Mansion-Review list facts ingest"
  & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts/run_mansion_review_listfacts_to_db.ps1") `
    -RepoPath $repo `
    -CityIds $CityIds `
    -Kinds $Kinds `
    -SleepSec $SleepSec `
    -MaxPages $MaxPages `
    -Merge "fill_only" `
    $(if($CreateMissingSafe){"-CreateMissingSafe"}) `
    -RunPublish:$false
  if ($LASTEXITCODE -ne 0) { throw "run_mansion_review_listfacts_to_db.ps1 failed" }

  $py = Join-Path $repo ".venv\Scripts\python.exe"
  if (-not (Test-Path $py)) { throw ".venv python not found: $py. Run scripts/setup.ps1 first." }

  $orientCsv = Join-Path $repo "data/manual/orient_building_facts.csv"
  if (Test-Path $orientCsv) {
    Write-Host "[STEP] Orient building facts ingest (fill_only): $orientCsv"
    & $py -m tatemono_map.building_registry.ingest_building_facts `
      --db $mainDb `
      --csv $orientCsv `
      --source orient_list_facts `
      --merge fill_only
    if ($LASTEXITCODE -ne 0) { throw "ingest_building_facts (Orient) failed" }
  } else {
    Write-Host "[STEP] Orient building facts ingest skipped (file not found): $orientCsv"
  }

  Write-Host "[STEP] publish_public"
  & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts/publish_public.ps1") -RepoPath $repo
  if ($LASTEXITCODE -ne 0) { throw "publish_public.ps1 failed" }

  $statsCode = @'
import sqlite3
import sys
from pathlib import Path


def latest_csv_rows(base: Path, pattern: str) -> int:
    files = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return 0
    with files[0].open("r", encoding="utf-8-sig", newline="") as fh:
        return max(0, sum(1 for _ in fh) - 1)


main_db = Path(sys.argv[1])
public_db = Path(sys.argv[2])
repo = Path(sys.argv[3])

with sqlite3.connect(main_db) as conn:
    buildings_total = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    listings_total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    buildings_with_listings = conn.execute(
        """
        SELECT COUNT(DISTINCT l.building_key)
        FROM listings l
        JOIN buildings b ON b.building_id = l.building_key
        WHERE l.building_key IS NOT NULL AND l.building_key <> ''
        """
    ).fetchone()[0]

with sqlite3.connect(public_db) as conn:
    vacancy_total = conn.execute("SELECT COALESCE(SUM(vacancy_count), 0) FROM building_summaries").fetchone()[0]

review_dir = repo / "tmp" / "review"
facts_total = latest_csv_rows(repo / "tmp" / "manual" / "outputs" / "mansion_review" / "combined", "building_facts_*.csv")
unresolved = latest_csv_rows(review_dir, "unmatched_building_facts_*.csv")
created = latest_csv_rows(review_dir, "created_buildings_*.csv")
matched = max(0, facts_total - unresolved)

print(f"[MVP_FINAL] buildings_total={buildings_total}")
print(f"[MVP_FINAL] listings_total={listings_total}")
print(f"[MVP_FINAL] vacancy_total={vacancy_total}")
print(f"[MVP_FINAL] buildings_with_listings={buildings_with_listings}")
print(f"[MVP_FINAL] mansion_review_facts_total={facts_total}")
print(f"[MVP_FINAL] mansion_review_matched={matched}")
print(f"[MVP_FINAL] mansion_review_unresolved={unresolved}")
print(f"[MVP_FINAL] mansion_review_created={created}")
'@

  Write-Host "[STEP] MVP final stats"
  & $py -c $statsCode $mainDb $publicDb $repo
  if ($LASTEXITCODE -ne 0) { throw "MVP final stats collection failed" }

  Write-Host "[STEP] doctor gate"
  & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts/run_mvp_doctor.ps1") -RepoPath $repo
  if ($LASTEXITCODE -ne 0) {
    $doctorStatus = "NG"
    Write-Host "DOCTOR=$doctorStatus"
    exit 1
  }

  $doctorStatus = "OK"
  Write-Host "OUT=$outDir"
  Write-Host "DOCTOR=$doctorStatus"
}
finally {
  Pop-Location
}
