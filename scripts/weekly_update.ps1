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
$env:PYTHONPATH = "src"

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


& $py -c "from tatemono_map.db.schema import ensure_schema; ensure_schema(r'$DbPath')"
if ($LASTEXITCODE -ne 0) { throw "failed to ensure schema compatibility" }

$rows = (Import-Csv -Path $MasterImportCsv).Count
$outDir = Split-Path -Parent $MasterImportCsv
Write-Host "[weekly_update] input_csv: $MasterImportCsv"
Write-Host "[weekly_update] outdir: $outDir"
Write-Host "[weekly_update] rows: $rows"
if ($rows -eq 0) {
  $msg = "new input not found / rows=0 (MasterImportCsv: $MasterImportCsv)"
  if ($QcMode -eq "strict") { throw $msg }
  Write-Warning $msg
  return
}

$beforeListings = & $py -c "import sqlite3; conn=sqlite3.connect(r'$DbPath'); print(conn.execute('SELECT COUNT(*) FROM listings').fetchone()[0]); conn.close()"
if ($LASTEXITCODE -ne 0) { throw "failed to read listings count before ingest" }
$beforeListings = [int]($beforeListings | Select-Object -Last 1)

$prevCurrent = & $py -c "import sqlite3; conn=sqlite3.connect(r'$DbPath'); row=conn.execute(\"SELECT ingest_run_id FROM current_ingest_snapshots WHERE source='master_import'\").fetchone(); print('' if row is None else row[0]); conn.close()"
if ($LASTEXITCODE -ne 0) { throw "failed to read current snapshot before ingest" }
$prevCurrent = ($prevCurrent | Select-Object -Last 1).Trim()

$ingestOutput = & $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --csv $MasterImportCsv --source master_import
if ($LASTEXITCODE -ne 0) { throw "ingest_master_import failed" }
$ingestLine = ($ingestOutput | Select-Object -Last 1)
Write-Host "[weekly_update] ingest: $ingestLine"
$runMatch = [regex]::Match($ingestLine, 'ingest_run_id=(\d+)')
if (-not $runMatch.Success) { throw "failed to parse ingest_run_id from ingest output" }
$newRunId = [int]$runMatch.Groups[1].Value

$afterListings = & $py -c "import sqlite3; conn=sqlite3.connect(r'$DbPath'); print(conn.execute('SELECT COUNT(*) FROM listings').fetchone()[0]); conn.close()"
if ($LASTEXITCODE -ne 0) { throw "failed to read listings count after ingest" }
$afterListings = [int]($afterListings | Select-Object -Last 1)
$newListings = $afterListings - $beforeListings
if ($newListings -le 0) {
  $msg = "ingest produced 0 new listings (before=$beforeListings after=$afterListings csv_rows=$rows)"
  if ($QcMode -eq "strict") { throw $msg }
  Write-Warning $msg
}

& $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --source master_import --set-current-run-id $newRunId
if ($LASTEXITCODE -ne 0) { throw "failed to switch current snapshot to run_id=$newRunId" }
Write-Host "[weekly_update] switched current snapshot: source=master_import run_id=$newRunId prev_run_id=$prevCurrent"

try {
  & (Join-Path $RepoPath "scripts\publish_public.ps1") -RepoPath $RepoPath
  if ($LASTEXITCODE -ne 0) { throw "publish_public failed" }
}
catch {
  if (-not [string]::IsNullOrWhiteSpace($prevCurrent)) {
    Write-Warning "[weekly_update] publish failed. restoring previous current snapshot run_id=$prevCurrent"
    & $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --source master_import --set-current-run-id $prevCurrent
  }
  throw
}

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
