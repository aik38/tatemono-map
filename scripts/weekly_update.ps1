param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$DbPath = "data/tatemono_map.sqlite3",
  [string]$MasterImportCsv = "",
  [string]$DownloadsDir = "Downloads",
  [ValidateSet("warn", "strict")]
  [string]$QcMode = "warn"
)

$ErrorActionPreference = "Stop"
Set-Location $RepoPath

$py = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (!(Test-Path $py)) { $py = "python" }

if ([string]::IsNullOrWhiteSpace($MasterImportCsv)) {
  & (Join-Path $RepoPath "scripts\run_pdf_zip_latest.ps1") -RepoPath $RepoPath -DownloadsDir $DownloadsDir -QcMode $QcMode
  if ($LASTEXITCODE -ne 0) { throw "run_pdf_zip_latest failed" }

  $latest = Get-ChildItem (Join-Path $RepoPath "tmp/pdf_pipeline/out") -Directory -ErrorAction Stop |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $latest) { throw "No out dir found under tmp/pdf_pipeline/out" }
  $MasterImportCsv = Join-Path $latest.FullName "master_import.csv"
}

if (-not (Test-Path $MasterImportCsv)) {
  throw "MasterImportCsv not found: $MasterImportCsv"
}

$rows = (Import-Csv -Path $MasterImportCsv).Count
$outDir = Split-Path -Parent $MasterImportCsv
Write-Host "[weekly_update] outdir: $outDir"
Write-Host "[weekly_update] rows: $rows"
if ($rows -eq 0) {
  throw "new input not found / rows=0 (MasterImportCsv: $MasterImportCsv)"
}

& $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --csv $MasterImportCsv --source master_import
if ($LASTEXITCODE -ne 0) { throw "ingest_master_import failed" }

& (Join-Path $RepoPath "scripts\publish_public.ps1") -RepoPath $RepoPath
if ($LASTEXITCODE -ne 0) { throw "publish_public failed" }

& $py -m tatemono_map.render.build --db-path $DbPath --output-dir (Join-Path $RepoPath "dist")
if ($LASTEXITCODE -ne 0) { throw "render.build failed" }
