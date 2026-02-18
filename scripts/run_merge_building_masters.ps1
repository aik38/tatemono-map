param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$PrimaryCsv = "",
  [string]$SecondaryCsv = "",
  [string]$OutCsv = "",
  [switch]$AddrOnlyFallback
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

if ([string]::IsNullOrWhiteSpace($PrimaryCsv)) {
  $PrimaryCsv = Join-Path $REPO "tmp/manual/inputs/buildings_master/buildings_master_primary.csv"
}
if ([string]::IsNullOrWhiteSpace($SecondaryCsv)) {
  $SecondaryCsv = Join-Path $REPO "tmp/manual/inputs/buildings_master/buildings_master_secondary.csv"
}
if ([string]::IsNullOrWhiteSpace($OutCsv)) {
  $OutCsv = Join-Path $REPO "tmp/manual/outputs/buildings_master/buildings_master.csv"
}

if (-not (Test-Path $PrimaryCsv)) { throw "Primary CSV not found: $PrimaryCsv" }
if (-not (Test-Path $SecondaryCsv)) { throw "Secondary CSV not found: $SecondaryCsv" }

$args = @(
  (Join-Path $REPO "scripts/merge_building_masters_primary_wins.py"),
  "--primary", $PrimaryCsv,
  "--secondary", $SecondaryCsv,
  "--out", $OutCsv
)

if ($AddrOnlyFallback) {
  $args += "--addr-only-fallback"
}

& $PY @args
