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
