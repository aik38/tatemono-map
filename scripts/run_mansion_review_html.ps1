param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$InputPath = "",
  [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$PY = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path $PY)) { throw ".venv python not found: $PY. Run scripts/setup.ps1 first." }

if ([string]::IsNullOrWhiteSpace($InputPath)) {
  $InputPath = Join-Path $RepoPath "tmp/manual/inputs/html_saved"
}
if ([string]::IsNullOrWhiteSpace($OutDir)) {
  $OutDir = Join-Path $RepoPath "tmp/manual/outputs/mansion_review"
}

& $PY (Join-Path $RepoPath "scripts/mansion_review_html_to_csv.py") --input $InputPath --out-dir $OutDir
