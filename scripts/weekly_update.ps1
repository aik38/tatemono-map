param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$DbPath = "data/tatemono_map.sqlite3",
  [string]$MasterImportCsv = "",
  [string]$DownloadsDir = (Join-Path $env:USERPROFILE "Downloads"),
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

$beforeListings = & $py -c "import sqlite3; conn=sqlite3.connect(r'$DbPath'); print(conn.execute('SELECT COUNT(*) FROM listings').fetchone()[0]); conn.close()"
if ($LASTEXITCODE -ne 0) { throw "failed to read listings count before ingest" }
$beforeListings = [int]($beforeListings | Select-Object -Last 1)

& $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --csv $MasterImportCsv --source master_import
if ($LASTEXITCODE -ne 0) { throw "ingest_master_import failed" }

$afterListings = & $py -c "import sqlite3; conn=sqlite3.connect(r'$DbPath'); print(conn.execute('SELECT COUNT(*) FROM listings').fetchone()[0]); conn.close()"
if ($LASTEXITCODE -ne 0) { throw "failed to read listings count after ingest" }
$afterListings = [int]($afterListings | Select-Object -Last 1)
$newListings = $afterListings - $beforeListings
if ($newListings -le 0) {
  $msg = "ingest produced 0 new listings (before=$beforeListings after=$afterListings csv_rows=$rows)"
  if ($QcMode -eq "strict") { throw $msg }
  Write-Warning $msg
}

& (Join-Path $RepoPath "scripts\publish_public.ps1") -RepoPath $RepoPath
if ($LASTEXITCODE -ne 0) { throw "publish_public failed" }

$publicDb = Join-Path $RepoPath "data/public/public.sqlite3"
$publicCheckCode = @'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
required = ("buildings", "building_summaries")
actual = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
missing = [table for table in required if table not in actual]
print("OK" if not missing else "MISSING:" + ",".join(missing))
conn.close()
'@
$publicCheck = & $py -c $publicCheckCode $publicDb
if ($LASTEXITCODE -ne 0) { throw "failed to validate public db schema" }
$publicCheck = ($publicCheck | Select-Object -Last 1)
if ($publicCheck -ne "OK") { throw "public DB missing required tables: $publicCheck" }

& $py -m tatemono_map.render.build --db-path $publicDb --output-dir (Join-Path $RepoPath "dist")
if ($LASTEXITCODE -ne 0) { throw "render.build failed" }
