param(
  [Parameter(Mandatory=$true)][string]$UlucksZip,
  [Parameter(Mandatory=$true)][string]$RealproZip,
  [Parameter(Mandatory=$true)][string]$OrientPdf,
  [string]$RepoPath = (Join-Path $env:USERPROFILE "tatemono-map"),
  [string]$OutDir = "",
  [ValidateSet("strict","warn","off")][string]$QcMode = "warn",
  [switch]$Open
)

$ErrorActionPreference="Stop"

Set-Location $RepoPath

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
  python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"

# install only pdf deps (project base deps are already handled by your usual dev/setup scripts)
python -m pip install -q --upgrade pip
python -m pip install -q -r .\requirements-pdf.txt

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$work = Join-Path $RepoPath "tmp\pdf_pipeline\work\$ts"
$ulDir = Join-Path $work "ulucks"
$rpDir = Join-Path $work "realpro"
New-Item -ItemType Directory -Force -Path $ulDir,$rpDir | Out-Null

Expand-Archive -Force -Path $UlucksZip -DestinationPath $ulDir
Expand-Archive -Force -Path $RealproZip -DestinationPath $rpDir

if ($OutDir -eq "") {
  $OutDir = Join-Path $RepoPath "tmp\pdf_pipeline\out\$ts"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

python -m tatemono_map.cli.pdf_batch_run `
  --ulucks-dir $ulDir `
  --realpro-dir $rpDir `
  --orient-pdf $OrientPdf `
  --qc-mode $QcMode `
  --out-dir $OutDir

if ($Open) {
  if (Test-Path (Join-Path $OutDir "final.csv")) { Start-Process (Join-Path $OutDir "final.csv") }
  if (Test-Path (Join-Path $OutDir "qc_report.txt")) { Start-Process (Join-Path $OutDir "qc_report.txt") }
  if (Test-Path (Join-Path $OutDir "stats.csv")) { Start-Process (Join-Path $OutDir "stats.csv") }
}
