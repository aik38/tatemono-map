param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$DbPath = "data/tatemono_map.sqlite3",
  [string]$MasterImportCsv = ""
)

$ErrorActionPreference = "Stop"
Set-Location $RepoPath

$py = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (!(Test-Path $py)) { $py = "python" }

if ([string]::IsNullOrWhiteSpace($MasterImportCsv)) {
  $latest = Get-ChildItem (Join-Path $RepoPath "tmp/pdf_pipeline/out") -Directory -ErrorAction Stop |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $latest) { throw "No out dir found under tmp/pdf_pipeline/out" }
  $MasterImportCsv = Join-Path $latest.FullName "master_import.csv"
}

& $py -m tatemono_map.cli.pdf_batch_run --out-dir (Split-Path -Parent $MasterImportCsv)
if ($LASTEXITCODE -ne 0) { throw "pdf_batch_run failed" }

& $py -m tatemono_map.building_registry.ingest_master_import --db $DbPath --csv $MasterImportCsv --source master_import
if ($LASTEXITCODE -ne 0) { throw "ingest_master_import failed" }

& (Join-Path $RepoPath "scripts\publish_public.ps1") -RepoPath $RepoPath
if ($LASTEXITCODE -ne 0) { throw "publish_public failed" }

& $py -m tatemono_map.render.build --db-path $DbPath --output-dir (Join-Path $RepoPath "dist")
if ($LASTEXITCODE -ne 0) { throw "render.build failed" }
