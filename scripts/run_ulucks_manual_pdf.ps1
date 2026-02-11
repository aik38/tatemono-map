param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE "tatemono-map"),
    [string]$CsvPath = "tmp/manual/ulucks_pdf_raw.csv",
    [string]$OutputDir = "dist",
    [switch]$NoServe
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $RepoPath)) {
    throw "RepoPath not found: $RepoPath"
}

Set-Location $RepoPath

if (-not $env:SQLITE_DB_PATH) {
    $env:SQLITE_DB_PATH = "data/tatemono_map.sqlite3"
}

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if (-not (Test-Path $CsvPath)) {
    throw "CSV not found: $CsvPath"
}

python -m tatemono_map.cli.ulucks_manual_run --csv $CsvPath --db $env:SQLITE_DB_PATH --output $OutputDir --no-serve:$NoServe

$indexPath = Join-Path $RepoPath "$OutputDir/index.html"
if (-not (Test-Path $indexPath)) {
    throw "build output missing: $indexPath"
}

Start-Process $indexPath
