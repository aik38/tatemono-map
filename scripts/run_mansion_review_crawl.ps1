param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$CityIds = "1616,1619",
  [string]$Kinds = "mansion,chintai",
  [string]$Mode = "list",
  [double]$SleepSec = 0.7,
  [int]$MaxPages = 0
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
  param([string]$Path)

  $resolved = Resolve-Path -Path $Path -ErrorAction Stop
  $fullPath = $resolved.Path
  if (-not (Test-Path (Join-Path $fullPath ".git"))) {
    throw "Not a git repository: $fullPath"
  }
  if (-not (Test-Path (Join-Path $fullPath "pyproject.toml"))) {
    throw "pyproject.toml not found. Refusing to run outside tatemono-map repo: $fullPath"
  }
  return $fullPath
}

$REPO = Resolve-RepoRoot -Path $RepoPath
Set-Location $REPO

$PY = Join-Path $REPO ".venv\Scripts\python.exe"
if (-not (Test-Path $PY)) { throw ".venv python not found: $PY. Run scripts/setup.ps1 first." }

& $PY (Join-Path $REPO "scripts/mansion_review_crawl_to_csv.py") `
  --city-ids $CityIds `
  --kinds $Kinds `
  --mode $Mode `
  --sleep-sec $SleepSec `
  --max-pages $MaxPages

<#
Example:
pwsh scripts/run_mansion_review_crawl.ps1 -CityIds "1616,1619" -Kinds "mansion,chintai" -Mode list -SleepSec 0.7 -MaxPages 0

Notes:
-MaxPages 0 : 自動ページング（ページネーションリンク推定。異常値時は次へ追跡で安全停止）
-MaxPages N : 明示 N ページまで収集（既知ページ数の確実運用）
#>
