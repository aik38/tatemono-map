param(
    [string]$RepoPath,
    [string]$Message,
    [ValidateSet('warn', 'strict')]
    [string]$RootCsvPolicy = 'warn'
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

function Get-TrackedMatches {
    param(
        [string]$RepoRoot,
        [string[]]$Patterns
    )

    $results = @()
    foreach ($pattern in $Patterns) {
        $matches = git -C $RepoRoot ls-files -- $pattern
        if ($matches) {
            $results += ($matches | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        }
    }

    return $results | Sort-Object -Unique
}

if ([string]::IsNullOrWhiteSpace($Message)) {
    throw 'Commit message is required. Use -Message "your commit message".'
}

$resolvedRepoPath = Resolve-RepoRoot -RequestedRepoPath $RepoPath
Set-Location $resolvedRepoPath

$forbiddenPatterns = @(
    'secrets/**',
    '.tmp/**',
    'ulucks_pdf_raw.csv',
    'mansion_review_*.csv'
)

$trackedForbidden = Get-TrackedMatches -RepoRoot $resolvedRepoPath -Patterns $forbiddenPatterns
if ($trackedForbidden.Count -gt 0) {
    Write-Host '[ERROR] Forbidden tracked files detected:' -ForegroundColor Red
    $trackedForbidden | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    throw 'Remove tracked forbidden files before commit/push.'
}

$rootCsvFiles = Get-ChildItem -LiteralPath $resolvedRepoPath -File -Filter '*.csv'
if ($rootCsvFiles.Count -gt 0) {
    $trackedRootCsv = git -C $resolvedRepoPath ls-files -- '*.csv'

    $csvNames = $rootCsvFiles | ForEach-Object { $_.Name }
    $msg = "Repository root has CSV files: $($csvNames -join ', '). Keep generated CSVs outside root."

    if ($RootCsvPolicy -eq 'strict') {
        throw $msg
    }

    Write-Warning $msg
    if ($trackedRootCsv) {
        Write-Warning ('Tracked root CSV files: ' + (($trackedRootCsv | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ', '))
    }
}

git status

$gitStatus = git status --porcelain
if (-not $gitStatus) {
    throw 'No changes to commit.'
}

git add -A
git commit -m $Message
git push
