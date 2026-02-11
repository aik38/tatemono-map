param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [string]$AuthFile = "secrets/ulucks_auth.json",
    [string]$DbPath = "data/tatemono_map.sqlite3",
    [int]$MaxPages = 200
)

$ErrorActionPreference = "Stop"
Write-Host "[EXPERIMENTAL] use scripts/run_ingest.ps1 -Mode smartlink_dom for production flow" -ForegroundColor Yellow

python -m tatemono_map.cli.ulucks_fetch_pw --url "$Url" --auth-file "$AuthFile" --db "$DbPath" --max-pages $MaxPages
python scripts/_experiments/parse_smartlink_page_to_listings.py --db-path "$DbPath"
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/ps/doctor.ps1 -DbPath "$DbPath"
