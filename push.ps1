param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE 'tatemono-map'),
    [string]$Message,
    [ValidateSet('warn', 'strict')]
    [string]$SensitiveColumnPolicy = 'warn'
)

$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot 'scripts/git_push.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Required script not found: $scriptPath"
}

& $scriptPath -RepoPath $RepoPath -Message $Message -SensitiveColumnPolicy $SensitiveColumnPolicy
