param(
  [Parameter(Mandatory = $true)]
  [string]$RepoPath,

  [string]$CsvPath
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path -LiteralPath $RepoPath).Path
$reviewDir = Join-Path $repo "tmp/review"
$outPath = Join-Path $reviewDir "unmatched_report_latest.txt"

function Write-Both {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.Generic.List[string]]$Lines,
    [Parameter(Mandatory = $true)]
    [string]$Text
  )
  Write-Host $Text
  [void]$Lines.Add($Text)
}

$lines = [System.Collections.Generic.List[string]]::new()

if (-not [string]::IsNullOrWhiteSpace($CsvPath)) {
  try {
    $targetCsv = (Resolve-Path -LiteralPath $CsvPath).Path
  }
  catch {
    Write-Both -Lines $lines -Text "[unmatched_report] 指定CSVが見つかりません: $CsvPath"
    $lines | Set-Content -LiteralPath $outPath -Encoding UTF8
    exit 0
  }
}
else {
  if (-not (Test-Path -LiteralPath $reviewDir)) {
    Write-Both -Lines $lines -Text "[unmatched_report] reviewディレクトリがありません: $reviewDir"
    $lines | Set-Content -LiteralPath $outPath -Encoding UTF8
    exit 0
  }

  $latest = Get-ChildItem -LiteralPath $reviewDir -File -Filter "unmatched_listings_*.csv" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

  if (-not $latest) {
    Write-Both -Lines $lines -Text "[unmatched_report] unmatched_listings_*.csv がありません: $reviewDir"
    $lines | Set-Content -LiteralPath $outPath -Encoding UTF8
    exit 0
  }

  $targetCsv = $latest.FullName
}

Write-Both -Lines $lines -Text "[unmatched_report] source: $targetCsv"
Write-Both -Lines $lines -Text ""

$rows = Import-Csv -LiteralPath $targetCsv

if (-not $rows -or $rows.Count -eq 0) {
  Write-Both -Lines $lines -Text "[unmatched_report] CSVは空です"
  $lines | Set-Content -LiteralPath $outPath -Encoding UTF8
  exit 0
}

function Show-Top {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IEnumerable]$Data,
    [Parameter(Mandatory = $true)]
    [string]$Column,
    [Parameter(Mandatory = $true)]
    [string]$Title,
    [Parameter(Mandatory = $true)]
    [int]$TopN,
    [Parameter(Mandatory = $true)]
    [System.Collections.Generic.List[string]]$Lines
  )

  Write-Both -Lines $Lines -Text "## $Title"

  $grouped = $Data |
    Group-Object -Property {
      $value = $_.$Column
      if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
        "<empty>"
      }
      else {
        ([string]$value).Trim()
      }
    } |
    Sort-Object Count -Descending |
    Select-Object -First $TopN

  if (-not $grouped) {
    Write-Both -Lines $Lines -Text "(no data)"
    Write-Both -Lines $Lines -Text ""
    return
  }

  $rank = 1
  foreach ($item in $grouped) {
    Write-Both -Lines $Lines -Text ("{0,2}. {1} : {2}" -f $rank, $item.Name, $item.Count)
    $rank += 1
  }

  Write-Both -Lines $Lines -Text ""
}

Write-Both -Lines $lines -Text ("total rows: {0}" -f $rows.Count)
Write-Both -Lines $lines -Text ""

Show-Top -Data $rows -Column "reason" -Title "reason 上位20" -TopN 20 -Lines $lines
Show-Top -Data $rows -Column "normalized_address" -Title "normalized_address 上位10" -TopN 10 -Lines $lines
Show-Top -Data $rows -Column "normalized_name" -Title "normalized_name 上位10" -TopN 10 -Lines $lines
Show-Top -Data $rows -Column "address" -Title "raw address 上位10" -TopN 10 -Lines $lines
Show-Top -Data $rows -Column "name" -Title "raw name 上位10" -TopN 10 -Lines $lines

$lines | Set-Content -LiteralPath $outPath -Encoding UTF8
Write-Host "[unmatched_report] report written: $outPath"
exit 0
