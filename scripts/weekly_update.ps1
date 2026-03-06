param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$DbPath = "data/tatemono_map.sqlite3",
  [string]$MasterImportCsv = "",
  [string]$DownloadsDir = (Join-Path $env:USERPROFILE "Downloads"),
  [ValidateSet("warn", "strict")]
  [string]$QcMode = "warn",
  [int]$MaxDropRatioPercent = 60,
  [int]$MaxUnmatchedOrSuspects = 200
)

$ErrorActionPreference = "Stop"
Set-Location $RepoPath
$env:PYTHONPATH = "src"

$py = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (!(Test-Path $py)) { $py = "python" }

function Invoke-QcGate {
  param(
    [bool]$Condition,
    [string]$Message,
    [string]$Mode
  )
  if ($Condition) {
    if ($Mode -eq "strict") { throw $Message }
    Write-Warning $Message
  }
}

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
$source = "master_import"
Write-Host "[weekly_update] source: $source"
Write-Host "[weekly_update] input_csv: $MasterImportCsv"
Write-Host "[weekly_update] outdir: $outDir"
Write-Host "[weekly_update] rows: $rows"
if ($rows -eq 0) {
  $msg = "new input not found / rows=0 (MasterImportCsv: $MasterImportCsv)"
  if ($QcMode -eq "strict") { throw $msg }
  Write-Warning $msg
  return
}

$statsCode = @'
import json
import sqlite3
import sys

path = sys.argv[1]
source = sys.argv[2]
new_run = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None

conn = sqlite3.connect(path)
cur = conn.cursor()
row = cur.execute("SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?", (source,)).fetchone()
current = row[0] if row else None
if current is None:
    source_listing_count = cur.execute("SELECT COUNT(*) FROM listings WHERE ingest_run_id IS NULL").fetchone()[0]
else:
    source_listing_count = cur.execute("SELECT COUNT(*) FROM listings WHERE ingest_run_id=?", (current,)).fetchone()[0]
active = cur.execute("SELECT source, ingest_run_id FROM current_ingest_snapshots ORDER BY source").fetchall()
vacancy_sum = cur.execute("SELECT COALESCE(SUM(vacancy_count),0) FROM building_summaries").fetchone()[0]
out = {
    "source": source,
    "current_run_id": current,
    "source_listing_count": source_listing_count,
    "current_snapshots": active,
    "vacancy_sum": vacancy_sum,
}
if new_run is not None:
    out["new_run_listings"] = cur.execute("SELECT COUNT(*) FROM listings WHERE ingest_run_id=?", (new_run,)).fetchone()[0]
print(json.dumps(out, ensure_ascii=False))
conn.close()
'@

$preStatsJson = & $py -c $statsCode $DbPath $source
if ($LASTEXITCODE -ne 0) { throw "failed to read pre-ingest stats" }
$preStats = ($preStatsJson | Select-Object -Last 1) | ConvertFrom-Json
$prevCurrent = if ($null -eq $preStats.current_run_id) { "" } else { [string]$preStats.current_run_id }
Write-Host "[weekly_update] current_snapshots(before): $($preStats.current_snapshots | ConvertTo-Json -Compress)"
Write-Host "[weekly_update] source_listing_count(before): $($preStats.source_listing_count)"
Write-Host "[weekly_update] vacancy_sum(before): $($preStats.vacancy_sum)"

$ingestOutput = & $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --csv $MasterImportCsv --source $source
if ($LASTEXITCODE -ne 0) { throw "ingest_master_import failed" }
$ingestLine = ($ingestOutput | Select-Object -Last 1)
Write-Host "[weekly_update] ingest: $ingestLine"
$runMatch = [regex]::Match($ingestLine, 'ingest_run_id=(\d+)')
if (-not $runMatch.Success) { throw "failed to parse ingest_run_id from ingest output" }
$newRunId = [int]$runMatch.Groups[1].Value

$susMatch = [regex]::Match($ingestLine, 'suspects=(\d+)')
$unmMatch = [regex]::Match($ingestLine, 'unmatched=(\d+)')
$attMatch = [regex]::Match($ingestLine, 'attached_listings=(\d+)')
$suspects = if ($susMatch.Success) { [int]$susMatch.Groups[1].Value } else { 0 }
$unmatched = if ($unmMatch.Success) { [int]$unmMatch.Groups[1].Value } else { 0 }
$attached = if ($attMatch.Success) { [int]$attMatch.Groups[1].Value } else { 0 }

Invoke-QcGate -Condition ($attached -eq 0) -Message "[weekly_update] source=$source attached_listings=0 (source-specific empty run). snapshot switch blocked." -Mode "strict"
Invoke-QcGate -Condition (($suspects + $unmatched) -gt $MaxUnmatchedOrSuspects) -Message "[weekly_update] source=$source suspects+unmatched abnormal: suspects=$suspects unmatched=$unmatched threshold=$MaxUnmatchedOrSuspects" -Mode $QcMode

$postStatsJson = & $py -c $statsCode $DbPath $source $newRunId
if ($LASTEXITCODE -ne 0) { throw "failed to read post-ingest stats" }
$postStats = ($postStatsJson | Select-Object -Last 1) | ConvertFrom-Json

$beforeCount = [int]$preStats.source_listing_count
$afterCount = [int]$postStats.new_run_listings
$dropRatio = if ($beforeCount -gt 0) { [int](100 * ($beforeCount - $afterCount) / $beforeCount) } else { 0 }
Invoke-QcGate -Condition (($beforeCount -gt 0) -and ($afterCount -eq 0)) -Message "[weekly_update] source=$source listing count collapsed to zero from $beforeCount. snapshot switch blocked." -Mode "strict"
Invoke-QcGate -Condition ($dropRatio -ge $MaxDropRatioPercent) -Message "[weekly_update] source=$source listing_count_drop=${dropRatio}% before=$beforeCount after=$afterCount" -Mode $QcMode

& $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --source $source --set-current-run-id $newRunId
if ($LASTEXITCODE -ne 0) { throw "failed to switch current snapshot to run_id=$newRunId" }
Write-Host "[weekly_update] qc: source=$source attached=$attached suspects=$suspects unmatched=$unmatched"
Write-Host "[weekly_update] switched current snapshot: source=$source run_id=$newRunId prev_run_id=$prevCurrent"

try {
  & (Join-Path $RepoPath "scripts\publish_public.ps1") -RepoPath $RepoPath
  if ($LASTEXITCODE -ne 0) { throw "publish_public failed" }
}
catch {
  if (-not [string]::IsNullOrWhiteSpace($prevCurrent)) {
    Write-Warning "[weekly_update] publish failed. restoring previous current snapshot run_id=$prevCurrent"
    & $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --source $source --set-current-run-id $prevCurrent
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

$finalStatsJson = & $py -c $statsCode $DbPath $source
if ($LASTEXITCODE -ne 0) { throw "failed to read final stats" }
$finalStats = ($finalStatsJson | Select-Object -Last 1) | ConvertFrom-Json
Write-Host "[weekly_update] publish_public: success"
Write-Host "[weekly_update] current_snapshots(after): $($finalStats.current_snapshots | ConvertTo-Json -Compress)"
Write-Host "[weekly_update] vacancy_sum(after): $($finalStats.vacancy_sum)"
