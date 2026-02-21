param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$DownloadsDir = (Join-Path $env:USERPROFILE "Downloads"),
  [ValidateSet("strict", "warn", "off")][string]$QcMode = "warn"
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

$realpro = Get-ChildItem $DownloadsDir -File | Where-Object Name -like "リアプロ-*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$ulucks = Get-ChildItem $DownloadsDir -File | Where-Object Name -like "ウラックス-*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $realpro) { throw "Not found: リアプロ-*.zip in $DownloadsDir" }
if (-not $ulucks) { throw "Not found: ウラックス-*.zip in $DownloadsDir" }

& (Join-Path $REPO "scripts/run_pdf_zip.ps1") -RepoPath $REPO -RealproZip $realpro.FullName -UlucksZip $ulucks.FullName -QcMode $QcMode

Write-Host ("[INFO] out-root: {0}" -f (Join-Path $REPO "tmp/pdf_pipeline/out"))
Write-Host "[INFO] expected files per run: final.csv, master_import.csv, manifest.csv, qc_report.txt, stats.csv"
