param(
    [string]$RepoPath
)

$scriptPath = Join-Path $PSScriptRoot 'git_sync.ps1'
& $scriptPath @PSBoundParameters
