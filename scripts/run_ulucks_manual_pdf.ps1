param(
    [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$CsvPath = "tmp/manual/ulucks_pdf_raw.csv",
    [string]$DbPath = "data/tatemono_map.sqlite3",
    [string]$OutputDir = "dist",
    [switch]$NoServe,
    [switch]$Open
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $RepoPath)) {
    throw "RepoPath not found: $RepoPath"
}

Set-Location $RepoPath

$env:SQLITE_DB_PATH = $DbPath

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if (-not (Test-Path $CsvPath)) {
    throw "CSV not found: $CsvPath"
}

$args = @(
    "--csv", $CsvPath,
    "--db", $env:SQLITE_DB_PATH,
    "--output", $OutputDir
)
if ($NoServe) {
    $args += "--no-serve"
}

python -m tatemono_map.cli.ulucks_manual_run @args

$indexPath = Join-Path $RepoPath "$OutputDir/index.html"
if (-not (Test-Path $indexPath)) {
    throw "build output missing: $indexPath"
}

if ($Open) {
    Start-Process $indexPath
}
