param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path)
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
if (-not (Test-Path $PY)) {
  python -m venv (Join-Path $REPO ".venv")
}

& $PY -m pip install --upgrade pip
& $PY -m pip install -r (Join-Path $REPO "requirements.txt")
& $PY -m pip install -r (Join-Path $REPO "requirements-pdf.txt")
& $PY -m pip install -r (Join-Path $REPO "requirements-dev.txt")
& $PY -m pip install -e $REPO

"[OK] setup completed: $PY"
