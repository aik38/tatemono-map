param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$DbPath,
  [string]$BuildingsMasterCsv,
  [string]$AliasCsv,
  [switch]$OpenIndex
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path $RepoPath).Path
$venvPath = Join-Path $repo ".venv"
if (-not (Test-Path $venvPath)) {
  throw ".venv not found: $venvPath"
}

if (-not $DbPath) {
  $DbPath = Join-Path $repo "data\tatemono_map.sqlite3"
}
if (-not $BuildingsMasterCsv) {
  $BuildingsMasterCsv = Join-Path $repo "tmp\manual\inputs\buildings_master.csv"
}
if (-not $AliasCsv) {
  $AliasCsv = Join-Path $repo "tmp\manual\inputs\building_key_aliases.csv"
}

$python = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$env:PYTHONPATH = Join-Path $repo "src"

& $python -m tatemono_map.normalize.building_summaries --db-path $DbPath --alias-csv $AliasCsv --buildings-master-csv $BuildingsMasterCsv
if ($LASTEXITCODE -ne 0) { throw "normalize.building_summaries failed" }

& $python -m tatemono_map.render.build --db-path $DbPath --output-dir (Join-Path $repo "dist") --version all
if ($LASTEXITCODE -ne 0) { throw "render.build failed" }

if ($OpenIndex) {
  Start-Process (Join-Path $repo "dist\index.html")
}
