param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$DbPath = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path $RepoPath).Path
if (-not $DbPath) { $DbPath = Join-Path $repo "data\tatemono_map.sqlite3" }

$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Push-Location $repo
try {
  & $py -m tatemono_map.cli.merge_duplicate_buildings --db $DbPath --review-dir (Join-Path $repo "tmp/review")
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
