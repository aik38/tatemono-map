param(
  [string]$RepoPath = (Get-Location).Path,
  [string[]]$CandidateRoots = @(),
  [string]$CanonicalCsv = "",
  [string]$AliasesCsv = ""
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path $RepoPath).Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Existing project Python environment missing" }
if ($CandidateRoots.Count -eq 0) {
  $CandidateRoots = @((Join-Path $repo "data"), (Join-Path $repo "backups"), (Join-Path $repo "tmp\backups"))
}
$env:PYTHONPATH = Join-Path $repo "src"
$auditArgs = @((Join-Path $repo "cloud\audit_master.py"), "--output", (Join-Path $repo "work\windows-master-candidates.json"))
foreach ($root in $CandidateRoots) { $auditArgs += @("--root", $root) }
if ($CanonicalCsv) { $auditArgs += @("--canonical-csv", $CanonicalCsv) }
if ($AliasesCsv) { $auditArgs += @("--aliases-csv", $AliasesCsv) }
& $python @auditArgs
if ($LASTEXITCODE -ne 0) { throw "Read-only master audit failed" }
Write-Host "Private inventory: $repo\work\windows-master-candidates.json. No DB was changed or selected automatically."
