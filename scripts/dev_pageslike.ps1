param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [int]$Port = 8787,
  [string]$Host = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

function Get-PythonCommand {
  param([string]$Repo)

  $venvPython = Join-Path $Repo ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    return $venvPython
  }

  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if (-not $pythonCmd) {
    throw "Python executable not found. Create .venv or install python."
  }

  return "python"
}

$repo = (Resolve-Path $RepoPath).Path
$distDir = Join-Path $repo "dist"
if (-not (Test-Path $distDir)) {
  throw "dist directory not found: $distDir`nRun scripts/dev_dist.ps1 first."
}

$tmpRoot = Join-Path $repo "tmp/dev_pageslike"
$pagesDir = Join-Path $tmpRoot "tatemono-map"

New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null
if (Test-Path $pagesDir) {
  Remove-Item -Path $pagesDir -Recurse -Force
}

$linkCreated = $false
if ($IsWindows) {
  try {
    New-Item -Path $pagesDir -ItemType Junction -Value $distDir -ErrorAction Stop | Out-Null
    $linkCreated = $true
    Write-Host "[dev_pageslike] Created junction: $pagesDir -> $distDir"
  }
  catch {
    Write-Warning "Failed to create junction. Falling back to copy. $($_.Exception.Message)"
  }
}
else {
  try {
    New-Item -Path $pagesDir -ItemType SymbolicLink -Value $distDir -ErrorAction Stop | Out-Null
    $linkCreated = $true
    Write-Host "[dev_pageslike] Created symlink: $pagesDir -> $distDir"
  }
  catch {
    Write-Warning "Failed to create symlink. Falling back to copy. $($_.Exception.Message)"
  }
}

if (-not $linkCreated) {
  Copy-Item -Path $distDir -Destination $pagesDir -Recurse -Force
  Write-Warning "Using copied dist snapshot in tmp/dev_pageslike/tatemono-map"
}

$python = Get-PythonCommand -Repo $repo
$url = "http://$Host`:$Port/tatemono-map/"
Write-Host "[dev_pageslike] Open: $url"
Write-Warning "do not open via file://"

& $python -m http.server $Port --bind $Host --directory $tmpRoot
