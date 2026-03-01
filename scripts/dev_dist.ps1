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
Set-Location $repo
$env:PYTHONPATH = "src"

$python = Get-PythonCommand -Repo $repo

Write-Host "[dev_dist] Generating dist from public DB..."
& pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts/publish_public.ps1") -RepoPath $repo
if ($LASTEXITCODE -ne 0) { throw "publish_public.ps1 failed" }

& $python -m tatemono_map.render.build --db-path data/public/public.sqlite3 --output-dir dist --version v2
if ($LASTEXITCODE -ne 0) { throw "tatemono_map.render.build failed" }

$buildInfoPath = Join-Path $repo "dist/build_info.json"
if (-not (Test-Path $buildInfoPath)) {
  throw "Guard failed: dist/build_info.json not found"
}

$buildingsPath = Join-Path $repo "dist/data/buildings.v2.min.json"
if (-not (Test-Path $buildingsPath)) {
  throw "Guard failed: dist/data/buildings.v2.min.json not found"
}

$buildingsCount = (& $python -c "import json; from pathlib import Path; p=Path(r'$buildingsPath'); print(len(json.loads(p.read_text(encoding='utf-8'))))" | Select-Object -Last 1)
if ([int]$buildingsCount -le 0) {
  throw "Guard failed: dist/data/buildings.v2.min.json has 0 items"
}

$url = "http://$Host`:$Port/index.html"
Write-Host "[dev_dist] dist guards OK: build_info.json exists, buildings.v2.min.json count=$buildingsCount"
Write-Host "[dev_dist] Open: $url"
Write-Warning "do not open via file://"

& $python -m http.server $Port --bind $Host --directory (Join-Path $repo "dist")
