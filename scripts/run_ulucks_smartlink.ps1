[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [int]$MaxItems = 200,
    [int]$Port = 8080,
    [switch]$NoServe
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $env:SQLITE_DB_PATH) {
    $env:SQLITE_DB_PATH = "data/tatemono_map.sqlite3"
}

python -m tatemono_map.cli.run_ulucks_pipeline --url $Url --db-path $env:SQLITE_DB_PATH --output-dir dist --max-items $MaxItems
if ($LASTEXITCODE -ne 0) { throw "pipeline failed" }

$indexPath = Join-Path (Get-Location) "dist/index.html"
if (-not (Test-Path $indexPath)) { throw "dist/index.html not found" }

if ($NoServe) {
    Start-Process $indexPath | Out-Null
    Write-Host "done: $indexPath"
} else {
    Start-Process "http://127.0.0.1:$Port/index.html" | Out-Null
    python -m http.server $Port --directory dist
}
