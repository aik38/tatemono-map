param(
  [Parameter(Mandatory = $true)]
  [string]$RepoPath,
  [string]$CsvPath = "",
  [string]$Message = ""
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path $RepoPath).Path
if (-not (Test-Path (Join-Path $repo ".git"))) {
  throw "Not a git repository: $repo"
}

Set-Location $repo
$env:PYTHONPATH = "src"

$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Python executable not found: $venvPython`nRun scripts/setup.ps1 first."
}

if ([string]::IsNullOrWhiteSpace($CsvPath)) {
  $latestCsv = Get-ChildItem -Path $repo -Filter "master_import.csv" -File -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $latestCsv) {
    throw "master_import.csv not found under repository: $repo"
  }
  $CsvPath = $latestCsv.FullName
}

if (-not (Test-Path $CsvPath)) {
  throw "CsvPath not found: $CsvPath"
}

$dbPath = Join-Path $repo "data\tatemono_map.sqlite3"
if (-not (Test-Path $dbPath)) {
  throw "Main DB not found: $dbPath"
}

& $venvPython -m tatemono_map.building_registry.ingest_master_import --db $dbPath --csv $CsvPath --source master_import
if ($LASTEXITCODE -ne 0) { throw "ingest_master_import failed" }

& pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\publish_public.ps1") -RepoPath $repo
if ($LASTEXITCODE -ne 0) { throw "publish_public.ps1 failed" }

& $venvPython -m tatemono_map.cli.export_buildings_json --db data/public/public.sqlite3 --out dist/data/buildings.v2.min.json --format v2min
if ($LASTEXITCODE -ne 0) { throw "export buildings.v2.min.json failed" }
& $venvPython -m tatemono_map.cli.export_buildings_json --db data/public/public.sqlite3 --out dist/data/buildings.json --format legacy
if ($LASTEXITCODE -ne 0) { throw "export buildings.json failed" }

$buildingsJsonCount = (& $venvPython -c "import json; from pathlib import Path; p=Path(r'dist/data/buildings.v2.min.json'); arr=json.loads(p.read_text(encoding='utf-8')); print(len(arr))") | Select-Object -Last 1
if ([int]$buildingsJsonCount -le 0) { throw "DoD failed: dist/data/buildings.v2.min.json has 0 entries" }
git add data/public/public.sqlite3 dist/data/buildings.v2.min.json dist/data/buildings.json

$hasChanges = (git diff --cached --name-only | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($hasChanges)) {
  Write-Host "No staged change in data/public/public.sqlite3. Nothing to commit or push."
  exit 0
}

$listingsMain = (& $venvPython -c "import sqlite3; c=sqlite3.connect(r'$dbPath'); print(c.execute('select count(*) from listings').fetchone()[0]); c.close()") | Select-Object -Last 1
$vacancyPublic = (& $venvPython -c "import sqlite3; c=sqlite3.connect(r'data/public/public.sqlite3'); print(c.execute('select coalesce(sum(vacancy_count),0) from building_summaries').fetchone()[0]); c.close()") | Select-Object -Last 1

if ([string]::IsNullOrWhiteSpace($Message)) {
  $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
  $Message = "publish public db ($timestamp) listings(main)=$listingsMain public.sum(vacancy_count)=$vacancyPublic"
}

git commit -m $Message
git push

Write-Host "Completed: ingest -> publish_public -> export_json -> guard(non-empty) -> commit(public.sqlite3+json) -> push"
Write-Host "CSV: $CsvPath"
Write-Host "Commit message: $Message"
Write-Host "PagesはGitHub Actionsで更新されます（反映は数十秒〜数分が目安）。"
Write-Host "確認コマンド: Invoke-WebRequest https://aik38.github.io/tatemono-map/index.html | Select-Object StatusCode,Headers"

