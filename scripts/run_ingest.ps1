[CmdletBinding()]
param(
  [string]$DbPath = "",
  [string]$BuildingKey = "demo",
  [string]$UluSmartlinkUrl = "",
  [switch]$SkipBuild,
  [switch]$FailIngest
)

$ErrorActionPreference = "Stop"
$HERE = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$REPO = (Resolve-Path (Join-Path $HERE "..")).Path
Set-Location $REPO

if ([string]::IsNullOrWhiteSpace($DbPath)) {
  if ($env:SQLITE_DB_PATH) { $DbPath = $env:SQLITE_DB_PATH }
  else { $DbPath = "data\tatemono_map.sqlite3" }
}
if (-not [System.IO.Path]::IsPathRooted($DbPath)) {
  $DbPath = Join-Path $REPO $DbPath
}
$DbPath = [System.IO.Path]::GetFullPath($DbPath)

$Py = Join-Path $REPO ".venv\Scripts\python.exe"
if (!(Test-Path $Py)) { $Py = "python" }

$SmartlinksFile = Join-Path $REPO "secrets\ulucks_smartlinks.txt"
$smartlinks = @()
if (-not [string]::IsNullOrWhiteSpace($UluSmartlinkUrl)) {
  $smartlinks += $UluSmartlinkUrl.Trim()
} elseif (Test-Path $SmartlinksFile) {
  $smartlinks += Get-Content $SmartlinksFile | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith("#") }
}

Write-Host "[ingest] repo=$REPO" -ForegroundColor DarkGray
Write-Host "[ingest] db=$DbPath key=$BuildingKey" -ForegroundColor Cyan

try {
  if ($smartlinks.Count -gt 0) {
    foreach ($url in $smartlinks) {
      & $Py -m tatemono_map.ingest.ulucks_smartlink --url $url --db $DbPath --limit 200
      if ($LASTEXITCODE -ne 0) { throw "ulucks ingest exited with code=$LASTEXITCODE" }
    }
    & $Py -m tatemono_map.parse.smartlink_page --db-path $DbPath
    if ($LASTEXITCODE -ne 0) { throw "parse exited with code=$LASTEXITCODE" }
    & $Py -m tatemono_map.normalize.building_summaries --db-path $DbPath
    if ($LASTEXITCODE -ne 0) { throw "normalize exited with code=$LASTEXITCODE" }
  } else {
    & $Py -m tatemono_map.ingest.stub --db $DbPath --building-key $BuildingKey
    if ($LASTEXITCODE -ne 0) { throw "fallback ingest exited with code=$LASTEXITCODE" }
  }
  Write-Host "[ingest] ok" -ForegroundColor Green
} catch {
  Write-Host "[ingest] FAILED (dist is kept as-is)" -ForegroundColor Red
  throw
}

if ($SkipBuild) {
  Write-Host "[build] skipped" -ForegroundColor Yellow
  exit 0
}

$dist = Join-Path $REPO "dist"
$tmp  = Join-Path $REPO "dist__tmp"
$next = Join-Path $REPO "dist__next"
$prev = Join-Path $REPO "dist__prev"
foreach ($p in @($tmp,$next,$prev)) {
  if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

New-Item -ItemType Directory -Path $tmp | Out-Null
Write-Host "[build] generating into $tmp" -ForegroundColor Cyan
& $Py -m tatemono_map.render.build --db-path $DbPath --output-dir $tmp
if ($LASTEXITCODE -ne 0) { throw "build exited with code=$LASTEXITCODE (dist kept as-is)" }

New-Item -ItemType Directory -Path $next | Out-Null
robocopy $tmp $next /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
$rc = $LASTEXITCODE
if ($rc -gt 7) { throw "robocopy tmp->next failed with exitcode=$rc (dist kept as-is)" }

if (Test-Path $dist) {
  if (Test-Path $prev) { Remove-Item $prev -Recurse -Force }
  Rename-Item -Path $dist -NewName (Split-Path $prev -Leaf)
}
Rename-Item -Path $next -NewName (Split-Path $dist -Leaf)

if (Test-Path $prev) { Remove-Item $prev -Recurse -Force }
if (Test-Path $tmp)  { Remove-Item $tmp  -Recurse -Force }
Write-Host "[done] ingest+build applied" -ForegroundColor Green
