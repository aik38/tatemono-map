param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [string]$AuthFile = "secrets/ulucks_auth.json",
    [string]$DbPath = "data/tatemono_map.sqlite3",
    [int]$MaxPages = 200
)

$ErrorActionPreference = "Stop"

python -m tatemono_map.cli.ulucks_fetch_pw --url "$Url" --auth-file "$AuthFile" --db "$DbPath" --max-pages $MaxPages
python scripts/parse_smartlink_page_to_listings.py --db-path "$DbPath"
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/ps/doctor.ps1 -DbPath "$DbPath"
