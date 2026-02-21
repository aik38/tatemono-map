param(
    [string]$RepoPath,
    [string]$Message,
    [switch]$AutoCommit,
    [ValidateSet('warn', 'strict')]
    [string]$SensitiveColumnPolicy = 'warn'
)

$scriptPath = Join-Path $PSScriptRoot 'git_push.ps1'
& $scriptPath @PSBoundParameters
