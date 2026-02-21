param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$PdfFinalCsv = "",
  [string]$MansionReviewUniqCsv = "",
  [string]$OutDir = "",
  [string]$OverridesCsv = ""
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

function Find-LatestPdfFinalCsv {
  param([string]$Repo)
  $outRoot = Join-Path $Repo "tmp/pdf_pipeline/out"
  $masterMatches = Get-ChildItem $outRoot -Recurse -File -Filter "master_import.csv" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending
  if ($masterMatches -and $masterMatches.Count -gt 0) {
    return $masterMatches[0].FullName
  }

  $finalMatches = Get-ChildItem $outRoot -Recurse -File -Filter "final.csv" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending
  if (-not $finalMatches -or $finalMatches.Count -eq 0) {
    throw "master_import.csv/final.csv not found under tmp/pdf_pipeline/out"
  }
  return $finalMatches[0].FullName
}

function Find-LatestMansionReviewUniqCsv {
  param([string]$Repo)
  $root = Join-Path $Repo "tmp/manual/outputs/mansion_review/combined"
  $matches = Get-ChildItem $root -File -Filter "mansion_review_master_UNIQ_*.csv" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending
  if (-not $matches -or $matches.Count -eq 0) {
    throw "mansion_review_master_UNIQ_*.csv not found under tmp/manual/outputs/mansion_review/combined"
  }
  return $matches[0].FullName
}

$REPO = Resolve-RepoRoot -Path $RepoPath
Set-Location $REPO

if ([string]::IsNullOrWhiteSpace($PdfFinalCsv)) {
  $PdfFinalCsv = Find-LatestPdfFinalCsv -Repo $REPO
}
if ([string]::IsNullOrWhiteSpace($MansionReviewUniqCsv)) {
  $MansionReviewUniqCsv = Find-LatestMansionReviewUniqCsv -Repo $REPO
}

if (-not (Test-Path $PdfFinalCsv)) { throw "PDF CSV not found: $PdfFinalCsv" }
if (-not (Test-Path $MansionReviewUniqCsv)) { throw "Mansion-review UNIQ CSV not found: $MansionReviewUniqCsv" }

if ([string]::IsNullOrWhiteSpace($OutDir)) {
  $ts = Get-Date -Format "yyyyMMdd_HHmmss"
  $OutDir = Join-Path $REPO "tmp/manual/outputs/buildings_master/$ts"
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$pyArgs = @(
  "-m", "tatemono_map.buildings_master.from_sources",
  "--pdf-final-csv", $PdfFinalCsv,
  "--mansion-review-uniq-csv", $MansionReviewUniqCsv,
  "--out-dir", $OutDir
)
if (-not [string]::IsNullOrWhiteSpace($OverridesCsv)) {
  $pyArgs += @("--overrides-csv", $OverridesCsv)
}

python @pyArgs
if ($LASTEXITCODE -ne 0) {
  throw "Failed: python $($pyArgs -join ' ')"
}

Write-Host "[DONE] buildings master generated: $OutDir"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1) Open suspects: $OutDir\buildings_master_suspects.csv"
Write-Host "2) Fill overrides template: $OutDir\buildings_master_overrides.template.csv"
Write-Host "3) Re-run with overrides:"
Write-Host "   pwsh -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -RepoPath $REPO -PdfFinalCsv '$PdfFinalCsv' -MansionReviewUniqCsv '$MansionReviewUniqCsv' -OutDir '$OutDir' -OverridesCsv '$OutDir\buildings_master_overrides.template.csv'"
Write-Host "4) Optional geocode enrich:"
Write-Host "   python -m tatemono_map.enrich.google_geocode --in '$OutDir\buildings_master.csv' --out '$OutDir\buildings_master_geocoded.csv'"
