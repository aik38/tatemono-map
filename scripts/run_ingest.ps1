# scripts/run_ingest.ps1
[CmdletBinding()]
param(
  [string]$DbPath = "",
  [string]$BuildingKey = "demo",
  [string]$UluSmartlinkUrl = "",
  [switch]$SkipBuild,
  [switch]$FailIngest
)

$ErrorActionPreference = "Stop"

# repo root（このファイル位置から確定：どこで実行してもOK）
$HERE = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$REPO = (Resolve-Path (Join-Path $HERE "..")).Path
Set-Location $REPO

# DB path: env > param > default
if ([string]::IsNullOrWhiteSpace($DbPath)) {
  if ($env:SQLITE_DB_PATH) { $DbPath = $env:SQLITE_DB_PATH }
  else { $DbPath = "data\tatemono_map.sqlite3" }
}
if (-not [System.IO.Path]::IsPathRooted($DbPath)) {
  $DbPath = Join-Path $REPO $DbPath
}
$DbPath = [System.IO.Path]::GetFullPath($DbPath)

# python: prefer local venv
$Py = Join-Path $REPO ".venv\Scripts\python.exe"
if (!(Test-Path $Py)) { $Py = "python" }

Write-Host "[ingest] repo=$REPO" -ForegroundColor DarkGray
Write-Host "[ingest] db=$DbPath key=$BuildingKey" -ForegroundColor Cyan

# ingest
if (-not [string]::IsNullOrWhiteSpace($UluSmartlinkUrl)) {
  $ingestArgs = @("-m","tatemono_map.ingest.ulucks_smartlink","--url",$UluSmartlinkUrl,"--limit","10","--db",$DbPath)
} else {
  $ingestArgs = @("-m","tatemono_map.ingest.stub","--db",$DbPath,"--building-key",$BuildingKey)
  if ($FailIngest) { $ingestArgs += "--fail" }
}

try {
  & $Py @ingestArgs
  if ($LASTEXITCODE -ne 0) { throw "ingest exited with code=$LASTEXITCODE" }
  Write-Host "[ingest] ok" -ForegroundColor Green
} catch {
  Write-Host "[ingest] FAILED (dist is kept as-is)" -ForegroundColor Red
  throw
}

if ($SkipBuild) {
  Write-Host "[build] skipped" -ForegroundColor Yellow
  exit 0
}

# build -> tmp, stage -> next, then swap into dist (distは成功時だけ更新)
$dist = Join-Path $REPO "dist"
$tmp  = Join-Path $REPO "dist__tmp"
$next = Join-Path $REPO "dist__next"
$prev = Join-Path $REPO "dist__prev"

foreach ($p in @($tmp,$next,$prev)) {
  if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

New-Item -ItemType Directory -Path $tmp | Out-Null

Write-Host "[build] generating into $tmp" -ForegroundColor Cyan
& $Py -m tatemono_map.render.build --output-dir $tmp
if ($LASTEXITCODE -ne 0) { throw "build exited with code=$LASTEXITCODE (dist kept as-is)" }

New-Item -ItemType Directory -Path $next | Out-Null
Write-Host "[build] staging tmp -> next" -ForegroundColor Cyan
robocopy $tmp $next /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
$rc = $LASTEXITCODE
if ($rc -gt 7) { throw "robocopy tmp->next failed with exitcode=$rc (dist kept as-is)" }

# swap: dist -> prev, next -> dist
if (Test-Path $dist) {
  if (Test-Path $prev) { Remove-Item $prev -Recurse -Force }
  Rename-Item -Path $dist -NewName (Split-Path $prev -Leaf)
}
Rename-Item -Path $next -NewName (Split-Path $dist -Leaf)

# cleanup
if (Test-Path $prev) { Remove-Item $prev -Recurse -Force }
if (Test-Path $tmp)  { Remove-Item $tmp  -Recurse -Force }

Write-Host "[done] ingest+build applied" -ForegroundColor Green
