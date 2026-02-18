param(
    [string]$RepoPath,
    [string]$Message,
    [ValidateSet('warn', 'strict')]
    [string]$RootCsvPolicy = 'warn'
)

$scriptPath = Join-Path $PSScriptRoot 'git_push.ps1'
& $scriptPath @PSBoundParameters
