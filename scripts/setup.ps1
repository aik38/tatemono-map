param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path)
)

$ErrorActionPreference = "Stop"

$PY = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path $PY)) {
  python -m venv (Join-Path $RepoPath ".venv")
}

& $PY -m pip install --upgrade pip
& $PY -m pip install -r (Join-Path $RepoPath "requirements.txt")
& $PY -m pip install -r (Join-Path $RepoPath "requirements-pdf.txt")
& $PY -m pip install -r (Join-Path $RepoPath "requirements-dev.txt")
& $PY -m pip install -e $RepoPath

"[OK] setup completed: $PY"
