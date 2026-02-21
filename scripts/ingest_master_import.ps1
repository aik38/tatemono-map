param(
  [string]$DbPath = "data/tatemono_map.sqlite3",
  [string]$CsvPath = "",
  [string]$Source = "master_import"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo

if ([string]::IsNullOrWhiteSpace($CsvPath)) {
  $latest = Get-ChildItem (Join-Path $repo "tmp/pdf_pipeline/out") -Directory -ErrorAction Stop |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $latest) { throw "No out dir found under tmp/pdf_pipeline/out" }
  $CsvPath = Join-Path $latest.FullName "master_import.csv"
}

$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --csv $CsvPath --source $Source
if ($LASTEXITCODE -ne 0) { throw "ingest_master_import failed" }
