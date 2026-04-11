param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$CityIds = "1616,1619",
  [string]$Kinds = "mansion,chintai",
  [double]$SleepSec = 0.7,
  [int]$MaxPages = 0,
  [string]$Merge = "fill_only",
  [switch]$AutoSeedHighConfidence = $false,
  [switch]$CreateMissingSafe = $false,
  [switch]$RunPublish = $true
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path $RepoPath).Path
if (-not (Test-Path (Join-Path $repo ".git"))) { throw "Not a git repository: $repo" }

& pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\run_mansion_review_facts_to_db.ps1") `
  -RepoPath $repo `
  -CityIds $CityIds `
  -Kinds $Kinds `
  -SleepSec $SleepSec `
  -MaxPages $MaxPages `
  -Merge $Merge `
  -RunPublish:$RunPublish
if ($LASTEXITCODE -ne 0) { throw "run_mansion_review_facts_to_db.ps1 failed" }
