param(
  [Parameter(Mandatory = $true)][string]$RealproZip,
  [Parameter(Mandatory = $true)][string]$UlucksZip,
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [ValidateSet("strict", "warn", "off")][string]$QcMode = "warn"
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
  param([string]$Path)

  $resolved = Resolve-Path -Path $Path -ErrorAction Stop
  $fullPath = $resolved.Path
  if (-not (Test-Path (Join-Path $fullPath ".git"))) {
    throw "Not a git repository: $fullPath"
  }
  if (-not (Test-Path (Join-Path $fullPath "pyproject.toml"))) {
    throw "pyproject.toml not found. Refusing to run outside tatemono-map repo: $fullPath"
  }
  return $fullPath
}

$REPO = Resolve-RepoRoot -Path $RepoPath
Set-Location $REPO

$PY = Join-Path $REPO ".venv\Scripts\python.exe"
if (-not (Test-Path $PY)) { throw ".venv python not found: $PY. Run scripts/setup.ps1 first." }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$work = Join-Path $REPO "tmp\pdf_pipeline\work\$ts"
$out = Join-Path $REPO "tmp\pdf_pipeline\out\$ts"
$extractRealpro = Join-Path $work "extract_realpro"
$extractUlucks = Join-Path $work "extract_ulucks"
$realproPdfs = Join-Path $work "realpro_pdfs"
$ulucksPdfs = Join-Path $work "ulucks_pdfs"

New-Item -ItemType Directory -Force -Path $extractRealpro, $extractUlucks, $realproPdfs, $ulucksPdfs, $out | Out-Null

Expand-Archive -Path (Resolve-Path $RealproZip) -DestinationPath $extractRealpro -Force
Expand-Archive -Path (Resolve-Path $UlucksZip) -DestinationPath $extractUlucks -Force

$idx = 0
Get-ChildItem $extractRealpro -Recurse -File -Filter *.pdf | ForEach-Object {
  $idx++
  $dest = Join-Path $realproPdfs (("{0:D4}_" -f $idx) + $_.Name)
  Copy-Item -Path $_.FullName -Destination $dest -Force
}
$idx = 0
Get-ChildItem $extractUlucks -Recurse -File -Filter *.pdf | ForEach-Object {
  $idx++
  $dest = Join-Path $ulucksPdfs (("{0:D4}_" -f $idx) + $_.Name)
  Copy-Item -Path $_.FullName -Destination $dest -Force
}

& $PY -m tatemono_map.cli.pdf_batch_run --realpro-dir $realproPdfs --ulucks-dir $ulucksPdfs --out-dir $out --qc-mode $QcMode

$finalCsv = Join-Path $out "final.csv"
$masterImportCsv = Join-Path $out "master_import.csv"
$statsCsv = Join-Path $out "stats.csv"
if (-not (Test-Path $finalCsv)) { throw "final.csv was not generated: $finalCsv" }
if (-not (Test-Path $masterImportCsv)) { throw "master_import.csv was not generated: $masterImportCsv" }
if (-not (Test-Path $statsCsv)) { throw "stats.csv was not generated: $statsCsv" }

$finalCount = (Import-Csv $finalCsv).Count
$masterRows = Import-Csv $masterImportCsv
$masterCount = $masterRows.Count
$warnCount = ((Import-Csv $statsCsv) | Where-Object { $_.status -eq "WARN" }).Count
# PS7互換のため char で先頭BOMのみ除去する
$masterHeader = (Get-Content -Path $masterImportCsv -TotalCount 1).TrimStart([char]0xFEFF)
if ($QcMode -eq "strict") {
  $expectedHeader = (& $PY -c "from tatemono_map.cli.pdf_batch_run import FINAL_SCHEMA; print(','.join(FINAL_SCHEMA))").Trim()
  if ($masterHeader -ne $expectedHeader) {
    throw "master_import.csv header mismatch in strict mode. got='$masterHeader' expected='$expectedHeader'"
  }
}
"[OK] out=$out"
"[OK] files=final.csv, master_import.csv, manifest.csv, qc_report.txt, stats.csv"
"[OK] final_rows=$finalCount"
"[OK] master_import_rows=$masterCount"
"[OK] master_import_header=$masterHeader"
"[OK] stats_warn_files=$warnCount"
