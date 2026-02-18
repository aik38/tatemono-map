param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE 'tatemono-map')
)

$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    param([string]$RequestedRepoPath)

    if ([string]::IsNullOrWhiteSpace($RequestedRepoPath)) {
        throw 'RepoPath is empty. Set -RepoPath or ensure $env:USERPROFILE\tatemono-map exists.'
    }

    $candidate = Resolve-Path -LiteralPath $RequestedRepoPath -ErrorAction SilentlyContinue
    if (-not $candidate) {
        throw "Repository path not found: $RequestedRepoPath`nExpected default: $(Join-Path $env:USERPROFILE 'tatemono-map')"
    }

    $fullPath = $candidate.Path
    if (-not (Test-Path (Join-Path $fullPath '.git'))) {
        throw "Not a git repository: $fullPath"
    }
    if (-not (Test-Path (Join-Path $fullPath 'pyproject.toml'))) {
        throw "pyproject.toml not found. Refusing to run outside tatemono-map repo: $fullPath"
    }

    return $fullPath
}

$resolvedRepoPath = Resolve-RepoRoot -RequestedRepoPath $RepoPath
Set-Location $resolvedRepoPath

git pull --ff-only
