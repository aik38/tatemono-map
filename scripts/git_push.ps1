param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE 'tatemono-map'),
    [string]$Message,
    [ValidateSet('warn', 'strict')]
    [string]$SensitiveColumnPolicy = 'warn'
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

function Test-SensitiveColumns {
    param(
        [string]$RepoRoot,
        [string]$Policy
    )

    $sensitiveColumns = @(
        'room_no',
        'room',
        'unit',
        '号室',
        'source_url',
        'sourceurl',
        'ref_url',
        'reference_url',
        'management_company',
        '管理会社'
    )

    $csvFiles = git -C $RepoRoot ls-files -- '*.csv' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    if (-not $csvFiles) { return }

    $hits = @()
    foreach ($csvPath in $csvFiles) {
        $abs = Join-Path $RepoRoot $csvPath
        if (-not (Test-Path -LiteralPath $abs)) { continue }

        $header = (Get-Content -LiteralPath $abs -TotalCount 1)
        if ([string]::IsNullOrWhiteSpace($header)) { continue }

        $columns = $header.Split(',') | ForEach-Object { $_.Trim('"').Trim() }
        $matched = $columns | Where-Object { $sensitiveColumns -contains $_ }
        if ($matched.Count -gt 0) {
            $hits += [pscustomobject]@{
                File = $csvPath
                Columns = ($matched -join ', ')
            }
        }
    }

    if ($hits.Count -eq 0) { return }

    $message = "Sensitive-looking CSV columns detected:`n" + (($hits | ForEach-Object { "  - $($_.File): $($_.Columns)" }) -join "`n")
    if ($Policy -eq 'strict') {
        throw $message
    }

    Write-Warning $message
}

if ([string]::IsNullOrWhiteSpace($Message)) {
    throw 'Commit message is required. Use -Message "your commit message".'
}

$resolvedRepoPath = Resolve-RepoRoot -RequestedRepoPath $RepoPath
Set-Location $resolvedRepoPath

$forbiddenPatterns = @(
    'secrets/**',
    '.tmp/**',
    'tmp/**'
)

$trackedForbidden = Get-TrackedMatches -RepoRoot $resolvedRepoPath -Patterns $forbiddenPatterns |
    Where-Object { $_ -notmatch '(^|/)\.gitkeep$' }

if ($trackedForbidden.Count -gt 0) {
    Write-Host '[ERROR] Forbidden tracked files detected:' -ForegroundColor Red
    $trackedForbidden | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    throw 'Remove tracked forbidden files before commit/push.'
}

$trackedRootCsv = git -C $resolvedRepoPath ls-files -- '*.csv' | Where-Object { $_ -notmatch '/' }
if ($trackedRootCsv) {
    Write-Host '[ERROR] Tracked CSV files at repository root are forbidden:' -ForegroundColor Red
    $trackedRootCsv | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    throw 'Remove tracked root CSV files before commit/push.'
}

Test-SensitiveColumns -RepoRoot $resolvedRepoPath -Policy $SensitiveColumnPolicy

git status

$gitStatus = git status --porcelain
if (-not $gitStatus) {
    throw 'No changes to commit.'
}

git add -A
git commit -m $Message
git push
