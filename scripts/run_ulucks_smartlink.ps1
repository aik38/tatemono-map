param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [int]$MaxItems = 200,
    [switch]$NoServe
)

$ErrorActionPreference = "Stop"

if (-not $env:SQLITE_DB_PATH) {
    $env:SQLITE_DB_PATH = "data/tatemono_map.sqlite3"
}

python -m tatemono_map.cli.ulucks_run --url $Url --db $env:SQLITE_DB_PATH --output dist --max-items $MaxItems
