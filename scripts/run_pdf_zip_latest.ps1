param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$DownloadsDir = (Join-Path $env:USERPROFILE "Downloads"),
  [ValidateSet("strict", "warn", "off")][string]$QcMode = "warn"
)

$ErrorActionPreference = "Stop"

$realpro = Get-ChildItem $DownloadsDir -File | Where-Object Name -like "リアプロ-*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$ulucks = Get-ChildItem $DownloadsDir -File | Where-Object Name -like "ウラックス-*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $realpro) { throw "Not found: リアプロ-*.zip in $DownloadsDir" }
if (-not $ulucks) { throw "Not found: ウラックス-*.zip in $DownloadsDir" }

& (Join-Path $RepoPath "scripts/run_pdf_zip.ps1") -RepoPath $RepoPath -RealproZip $realpro.FullName -UlucksZip $ulucks.FullName -QcMode $QcMode
