param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$CityIds = "1616,1619",
  [string]$Kinds = "mansion,chintai",
  [double]$SleepSec = 0.7,
  [int]$MaxPages = 3,
  [string]$Merge = "fill_only"
)

$ErrorActionPreference = "Stop"

if ($MaxPages -le 0) {
  throw "MaxPages must be > 0 for safe/reproducible operation."
}

$repo = (Resolve-Path $RepoPath).Path
if (-not (Test-Path (Join-Path $repo ".git"))) { throw "Not a git repository: $repo" }
if (-not (Test-Path (Join-Path $repo "pyproject.toml"))) { throw "pyproject.toml not found: $repo" }

Set-Location $repo
$env:PYTHONPATH = "src"

$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw ".venv python not found: $py. Run scripts/setup.ps1 first." }

& $py (Join-Path $repo "scripts/mansion_review_crawl_to_csv.py") `
  --city-ids $CityIds `
  --kinds $Kinds `
  --mode facts `
  --sleep-sec $SleepSec `
  --max-pages $MaxPages
if ($LASTEXITCODE -ne 0) { throw "mansion_review_crawl_to_csv.py failed" }

$factsCsv = Get-ChildItem -Path (Join-Path $repo "tmp\manual\outputs\mansion_review\combined") -Filter "building_facts_*.csv" -File |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if (-not $factsCsv) { throw "building_facts CSV not found under tmp/manual/outputs/mansion_review/combined" }
Write-Host "[OK] facts_csv=$($factsCsv.FullName)"

$dbPath = Join-Path $repo "data\tatemono_map.sqlite3"
& $py -m tatemono_map.building_registry.ingest_building_facts --db $dbPath --csv $factsCsv.FullName --source mansion_review_facts --merge $Merge
if ($LASTEXITCODE -ne 0) { throw "ingest_building_facts failed" }
Write-Host "[OK] ingest_building_facts db=$dbPath merge=$Merge"

& pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\publish_public.ps1") -RepoPath $repo
if ($LASTEXITCODE -ne 0) { throw "publish_public.ps1 failed" }
Write-Host "[OK] publish_public data/public/public.sqlite3"

& $py -m tatemono_map.cli.export_buildings_json --db data/public/public.sqlite3 --out dist/data/buildings.v2.min.json --format v2min
if ($LASTEXITCODE -ne 0) { throw "export buildings.v2.min.json failed" }
& $py -m tatemono_map.cli.export_buildings_json --db data/public/public.sqlite3 --out dist/data/buildings.json --format legacy
if ($LASTEXITCODE -ne 0) { throw "export buildings.json failed" }
Write-Host "[OK] dist export: dist/data/buildings.v2.min.json"
Write-Host "[OK] dist export: dist/data/buildings.json"
