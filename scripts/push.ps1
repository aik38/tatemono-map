param(
    [string]$RepoPath,
    [string]$Message,
    [ValidateSet('warn', 'strict')]
    [string]$SensitiveColumnPolicy = 'warn'
)

$scriptPath = Join-Path $PSScriptRoot 'git_push.ps1'
& $scriptPath @PSBoundParameters
