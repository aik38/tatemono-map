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

function Test-PathAllowedInTmp {
    param([string]$RelativePath)

    if ($RelativePath -match '(^|/)\.gitkeep$') {
        return $true
    }

    return $RelativePath -eq 'tmp/manual/README.md'
}

$forbiddenPatterns = @('secrets/**', '.tmp/**', 'tmp/**')
$forbiddenTracked = @()
foreach ($pattern in $forbiddenPatterns) {
    $matches = git -C $resolvedRepoPath ls-files -- $pattern
    if ($matches) {
        $forbiddenTracked += ($matches | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
}
$forbiddenTracked = $forbiddenTracked | Sort-Object -Unique |
    Where-Object {
        if ($_ -notlike 'tmp/*') {
            return $true
        }

        return -not (Test-PathAllowedInTmp -RelativePath $_)
    }

$trackedRootCsv = git -C $resolvedRepoPath ls-files -- '*.csv' | Where-Object { $_ -notmatch '/' }
$rootCsvFiles = Get-ChildItem -LiteralPath $resolvedRepoPath -File -Filter '*.csv'

Write-Host "Repo: $resolvedRepoPath"
if ($forbiddenTracked.Count -gt 0) {
    Write-Host 'Forbidden tracked files:' -ForegroundColor Red
    $forbiddenTracked | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host 'Fix:' -ForegroundColor Yellow
    Write-Host '  git rm --cached <path>' -ForegroundColor Yellow
    Write-Host '  (for tmp artifacts: git rm --cached -r tmp)' -ForegroundColor Yellow
} else {
    Write-Host 'Forbidden tracked files: none' -ForegroundColor Green
}

if ($trackedRootCsv) {
    Write-Host 'Tracked CSV files at repository root (forbidden):' -ForegroundColor Red
    $trackedRootCsv | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host 'Fix: git rm --cached <root_csv_file>' -ForegroundColor Yellow
} else {
    Write-Host 'Tracked CSV files at repository root: none' -ForegroundColor Green
}

if ($rootCsvFiles.Count -gt 0) {
    Write-Host 'Working tree root CSV files present:' -ForegroundColor Yellow
    $rootCsvFiles | ForEach-Object { Write-Host "  - $($_.Name)" -ForegroundColor Yellow }
} else {
    Write-Host 'Working tree root CSV files present: none' -ForegroundColor Green
}
