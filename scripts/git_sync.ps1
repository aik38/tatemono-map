param(
    [string]$RepoPath
)

$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    param([string]$RequestedRepoPath)

    if (-not [string]::IsNullOrWhiteSpace($RequestedRepoPath)) {
        $candidate = Resolve-Path -LiteralPath $RequestedRepoPath -ErrorAction SilentlyContinue
        if (-not $candidate) {
            throw "Repo path not found: $RequestedRepoPath"
        }
        $fullPath = $candidate.Path
        if (-not (Test-Path (Join-Path $fullPath '.git'))) {
            throw "Not a git repository: $fullPath"
        }
        return $fullPath
    }

    $candidates = @(
        $PSScriptRoot,
        (Split-Path -Parent $PSScriptRoot),
        (Get-Location).Path
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

    foreach ($candidatePath in $candidates) {
        $resolved = Resolve-Path -LiteralPath $candidatePath -ErrorAction SilentlyContinue
        if (-not $resolved) { continue }

        $dir = $resolved.Path
        while ($true) {
            if (Test-Path (Join-Path $dir '.git')) {
                return $dir
            }

            $parent = Split-Path -Parent $dir
            if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $dir) {
                break
            }
            $dir = $parent
        }
    }

    throw 'Could not auto-resolve repository root. Use -RepoPath explicitly.'
}

$resolvedRepoPath = Resolve-RepoRoot -RequestedRepoPath $RepoPath
Set-Location $resolvedRepoPath

git pull --ff-only
