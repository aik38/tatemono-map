param(
  [string]$DbPath = "data/tatemono_map.sqlite3",
  [string]$CsvPath = "tmp/manual/inputs/buildings_seed_ui.csv",
  [string]$Source = "ui_seed"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo

$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -m tatemono_map.building_registry.seed_from_ui --db $DbPath --csv $CsvPath --source $Source
if ($LASTEXITCODE -ne 0) { throw "seed_from_ui failed" }
