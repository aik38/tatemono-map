param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path),
  [string]$PdfFinalCsv = "",
  [string]$MansionReviewUniqCsv = "",
  [string]$OutDir = ""
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

function Normalize-Text {
  param([string]$Value)
  if ($null -eq $Value) { return "" }
  $s = $Value.Replace("　", " ").Trim().ToLowerInvariant()
  return ([regex]::Replace($s, "\s+", " "))
}

function Build-Key {
  param([string]$BuildingName, [string]$Address)
  return "$(Normalize-Text $BuildingName)|$(Normalize-Text $Address)"
}

function Find-LatestPdfFinalCsv {
  param([string]$Repo)
  $matches = Get-ChildItem (Join-Path $Repo "tmp/pdf_pipeline/out") -Recurse -File -Filter "final.csv" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending
  if (-not $matches -or $matches.Count -eq 0) {
    throw "final.csv not found under tmp/pdf_pipeline/out"
  }
  return $matches[0].FullName
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

if (-not (Test-Path $PdfFinalCsv)) { throw "PDF final.csv not found: $PdfFinalCsv" }
if (-not (Test-Path $MansionReviewUniqCsv)) { throw "Mansion-review UNIQ CSV not found: $MansionReviewUniqCsv" }

if ([string]::IsNullOrWhiteSpace($OutDir)) {
  $ts = Get-Date -Format "yyyyMMdd_HHmmss"
  $OutDir = Join-Path $REPO "tmp/manual/outputs/buildings_master/$ts"
}
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$pdfRows = Import-Csv $PdfFinalCsv
$mrRows = Import-Csv $MansionReviewUniqCsv

# 1) raw: final.csv を建物キーで集約
$rawMap = @{}
foreach ($row in $pdfRows) {
  $bn = ("" + $row.building_name).Trim()
  $ad = ("" + $row.address).Trim()
  $key = Build-Key -BuildingName $bn -Address $ad
  if ([string]::IsNullOrWhiteSpace($key.Replace("|", ""))) { continue }

  if (-not $rawMap.ContainsKey($key)) {
    $rawMap[$key] = [ordered]@{
      building_name = $bn
      address = $ad
      source = "pdf_pipeline"
      source_rows = 0
      mr_detail_url_evidence = ""
    }
  }
  $rawMap[$key].source_rows = [int]$rawMap[$key].source_rows + 1
}
$rawRows = $rawMap.Values | Sort-Object address, building_name
$rawCsv = Join-Path $OutDir "buildings_master_raw.csv"
$rawRows | Export-Csv $rawCsv -NoTypeInformation -Encoding utf8BOM

# 2) merged: raw + mansion-review UNIQ を統合
$mergedMap = @{}
foreach ($row in $rawRows) {
  $key = Build-Key -BuildingName $row.building_name -Address $row.address
  $mergedMap[$key] = [ordered]@{
    building_name = $row.building_name
    address = $row.address
    source = "pdf_pipeline"
    source_rows = [int]$row.source_rows
    mr_detail_url_evidence = ""
  }
}

foreach ($row in $mrRows) {
  $bn = ("" + $row.building_name).Trim()
  $ad = ("" + $row.address).Trim()
  $du = ("" + $row.detail_url).Trim()
  $key = Build-Key -BuildingName $bn -Address $ad
  if ([string]::IsNullOrWhiteSpace($key.Replace("|", ""))) { continue }

  if (-not $mergedMap.ContainsKey($key)) {
    $mergedMap[$key] = [ordered]@{
      building_name = $bn
      address = $ad
      source = "mansion_review"
      source_rows = 0
      mr_detail_url_evidence = $du
    }
  } else {
    if ($mergedMap[$key].source -notmatch "mansion_review") {
      $mergedMap[$key].source = "pdf_pipeline+mansion_review"
    }
    if (-not [string]::IsNullOrWhiteSpace($du)) {
      $existing = ("" + $mergedMap[$key].mr_detail_url_evidence).Trim()
      if ([string]::IsNullOrWhiteSpace($existing)) {
        $mergedMap[$key].mr_detail_url_evidence = $du
      }
    }
  }
  $mergedMap[$key].source_rows = [int]$mergedMap[$key].source_rows + 1
}

$mergedRows = $mergedMap.Values | Sort-Object address, building_name
$mergedCsv = Join-Path $OutDir "buildings_master_merged.csv"
$mergedRows | Export-Csv $mergedCsv -NoTypeInformation -Encoding utf8BOM

# 3) master: 公開向け最終列
$masterRows = foreach ($row in $mergedRows) {
  [ordered]@{
    building_name = $row.building_name
    address = $row.address
    source = $row.source
    source_rows = $row.source_rows
    mr_detail_url_evidence = $row.mr_detail_url_evidence
  }
}
$masterCsv = Join-Path $OutDir "buildings_master.csv"
$masterRows | Export-Csv $masterCsv -NoTypeInformation -Encoding utf8BOM

$stats = [ordered]@{
  generated_at = (Get-Date).ToString("s")
  inputs = [ordered]@{
    pdf_final_csv = $PdfFinalCsv
    mansion_review_uniq_csv = $MansionReviewUniqCsv
  }
  counts = [ordered]@{
    pdf_rows = @($pdfRows).Count
    mansion_review_rows = @($mrRows).Count
    raw_unique_buildings = @($rawRows).Count
    merged_unique_buildings = @($mergedRows).Count
  }
  outputs = [ordered]@{
    out_dir = $OutDir
    raw_csv = $rawCsv
    merged_csv = $mergedCsv
    buildings_master_csv = $masterCsv
  }
}
$statsPath = Join-Path $OutDir "stats.json"
$stats | ConvertTo-Json -Depth 8 | Set-Content -Path $statsPath -Encoding UTF8

Write-Host "[OK] raw=$rawCsv"
Write-Host "[OK] merged=$mergedCsv"
Write-Host "[OK] master=$masterCsv"
Write-Host "[OK] stats=$statsPath"
