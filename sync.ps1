param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE 'tatemono-map')
)

$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot 'scripts/git_sync.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Required script not found: $scriptPath"
}

& $scriptPath -RepoPath $RepoPath
