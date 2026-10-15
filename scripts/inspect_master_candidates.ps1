param(
  [string]$RepoPath = (Get-Location).Path,
  [string[]]$CandidateRoots = @(),
  [string]$CanonicalCsv = "",
  [string]$AliasesCsv = "",
  [switch]$ExportSnapshots
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path $RepoPath).Path
$codeRepo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Existing project Python environment missing" }
if ($CandidateRoots.Count -eq 0) {
  $CandidateRoots = @((Join-Path $repo "data"), (Join-Path $repo "backups"), (Join-Path $repo "tmp\backups"))
}
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $codeRepo "src"
$auditArgs = @((Join-Path $codeRepo "cloud\audit_master.py"), "--output", (Join-Path $codeRepo "work\windows-master-candidates.json"))
foreach ($root in $CandidateRoots) { $auditArgs += @("--root", $root) }
if ($CanonicalCsv) { $auditArgs += @("--canonical-csv", $CanonicalCsv) }
if ($AliasesCsv) { $auditArgs += @("--aliases-csv", $AliasesCsv) }
if ($ExportSnapshots) { $auditArgs += @("--snapshot-dir", (Join-Path $codeRepo "work\windows-snapshots")) }
try {
  & $python @auditArgs
  if ($LASTEXITCODE -ne 0) { throw "Read-only master audit failed" }
} finally {
  $env:PYTHONPATH = $previousPythonPath
}
Write-Host "Private inventory: $codeRepo\work\windows-master-candidates.json. Source DBs were not changed or selected automatically."
if ($ExportSnapshots) { Write-Host "Standalone copies: $codeRepo\work\windows-snapshots. Upload together with private CSVs to Cloud Shell work/initial-input." }
