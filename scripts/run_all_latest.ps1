param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$DownloadsDir = (Join-Path $env:USERPROFILE "Downloads"),
  [ValidateSet("strict", "warn", "off")][string]$QcMode = "warn",
  [switch]$SkipPush
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path -Path $RepoPath).Path
if (-not (Test-Path (Join-Path $repo ".git"))) {
  throw "Not a git repository: $repo"
}

Set-Location $repo

pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "sync.ps1") -RepoPath $repo
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts/run_pdf_zip_latest.ps1") -RepoPath $repo -DownloadsDir $DownloadsDir -QcMode $QcMode

$outRoot = Join-Path $repo "tmp/pdf_pipeline/out"
$latestCsv = Get-ChildItem -Path $outRoot -Filter "master_import.csv" -File -Recurse |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

if (-not $latestCsv) {
  throw "master_import.csv not found under $outRoot"
}

pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts/run_to_pages.ps1") -RepoPath $repo -CsvPath $latestCsv.FullName

$publicDb = Join-Path $repo "data/public/public.sqlite3"
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Python executable not found: $venvPython"
}

& $venvPython -c "import sqlite3; c=sqlite3.connect(r'$publicDb'); print('label_入居_count=', c.execute(\"select count(*) from building_summaries where coalesce(trim(building_availability_label),'')='入居'\").fetchone()[0]); rows=c.execute(\"select name, building_availability_label from building_summaries where coalesce(trim(building_availability_label),'')='入居' order by updated_at desc, name limit 10\").fetchall(); [print(f'{n}\t{l}') for n,l in rows]; c.close()"

if ($SkipPush) {
  Write-Host "run_to_pages.ps1 completed (already pushed)."
}

Write-Host "run_all_latest completed"
Write-Host "master_import.csv: $($latestCsv.FullName)"
