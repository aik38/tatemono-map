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

function Get-RequirementsFingerprint {
  param([string]$RepoRoot)

  $files = @(
    'requirements.txt',
    'requirements-pdf.txt',
    'requirements-dev.txt'
  )

  $parts = @()
  foreach ($file in $files) {
    $abs = Join-Path $RepoRoot $file
    if (Test-Path -LiteralPath $abs) {
      $hash = (Get-FileHash -LiteralPath $abs -Algorithm SHA256).Hash
      $parts += "${file}:$hash"
    } else {
      $parts += "$file:MISSING"
    }
  }

  $joined = ($parts -join "`n")
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($joined)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $digest = $sha.ComputeHash($bytes)
  } finally {
    $sha.Dispose()
  }

  return ([System.BitConverter]::ToString($digest) -replace '-', '').ToLowerInvariant()
}

$REPO = Resolve-RepoRoot -Path $RepoPath
Set-Location $REPO

$venvPath = Join-Path $REPO '.venv'
$PY = Join-Path $venvPath 'Scripts\python.exe'
$hashFile = Join-Path $venvPath '.requirements_hash'
$currentHash = Get-RequirementsFingerprint -RepoRoot $REPO

$venvExists = Test-Path -LiteralPath $PY
if (-not $venvExists) {
  python -m venv $venvPath
}

$shouldInstall = $true
if ($venvExists -and (Test-Path -LiteralPath $hashFile)) {
  $storedHash = (Get-Content -LiteralPath $hashFile -Raw).Trim()
  if ($storedHash -eq $currentHash) {
    $shouldInstall = $false
  }
}

if (-not $shouldInstall) {
  "[OK] setup skipped: requirements unchanged (.venv already prepared)."
  "[OK] python: $PY"
  exit 0
}

& $PY -m pip install --upgrade pip
& $PY -m pip install -r (Join-Path $REPO 'requirements.txt')
& $PY -m pip install -r (Join-Path $REPO 'requirements-pdf.txt')
& $PY -m pip install -r (Join-Path $REPO 'requirements-dev.txt')
& $PY -m pip install -e $REPO

Set-Content -LiteralPath $hashFile -Value $currentHash -NoNewline
"[OK] setup completed: $PY"

