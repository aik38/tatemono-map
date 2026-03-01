param(
  [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$PagesBuildInfoUrl = "https://aik38.github.io/tatemono-map/build_info.json"
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path $RepoPath).Path
$localPath = Join-Path $repo "dist/build_info.json"

if (-not (Test-Path $localPath)) {
  throw "Local build info not found: $localPath"
}

$local = Get-Content -Path $localPath -Raw -Encoding UTF8 | ConvertFrom-Json
$pagesRaw = curl.exe -fsSL $PagesBuildInfoUrl
$pages = $pagesRaw | ConvertFrom-Json

$localGitSha = [string]$local.git_sha
$pagesGitSha = [string]$pages.git_sha

$hasBothGitSha = -not [string]::IsNullOrWhiteSpace($localGitSha) -and -not [string]::IsNullOrWhiteSpace($pagesGitSha)
if ($hasBothGitSha) {
  if ($localGitSha -eq $pagesGitSha) {
    Write-Host "Parity OK (git_sha): $localGitSha"
    exit 0
  }

  Write-Error "Parity mismatch (git_sha):`n  local=$localGitSha`n  pages=$pagesGitSha"
  exit 1
}

$localBuildings = [int]$local.buildings_count
$pagesBuildings = [int]$pages.buildings_count
$localVacancy = [int]$local.vacancy_total
$pagesVacancy = [int]$pages.vacancy_total

$matchBuildings = ($localBuildings -eq $pagesBuildings)
$matchVacancy = ($localVacancy -eq $pagesVacancy)

if ($matchBuildings -and $matchVacancy) {
  Write-Host "Parity OK (fallback counts): buildings_count=$localBuildings vacancy_total=$localVacancy"
  exit 0
}

Write-Error @"
Parity mismatch (fallback counts):
  buildings_count: local=$localBuildings pages=$pagesBuildings
  vacancy_total:   local=$localVacancy pages=$pagesVacancy
"@
exit 1
