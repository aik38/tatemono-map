param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE 'tatemono-map'),
    [string]$Message,
    [switch]$AutoCommit,
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

function Test-PathAllowedInTmp {
    param([string]$RelativePath)

    $allowedTrackedTmpPaths = @(
        'tmp/manual/README.md',
        'tmp/manual/.gitkeep',
        'tmp/manual/inputs/.gitkeep',
        'tmp/manual/inputs/pdf_zips/.gitkeep',
        'tmp/manual/inputs/html_saved/.gitkeep',
        'tmp/manual/inputs/legacy_master_rebuild/.gitkeep',
        'tmp/manual/outputs/.gitkeep',
        'tmp/manual/outputs/mansion_review/.gitkeep',
        'tmp/manual/outputs/legacy_master_rebuild/.gitkeep',
        'tmp/pdf_pipeline/.gitkeep',
        'tmp/pdf_pipeline/work/.gitkeep',
        'tmp/pdf_pipeline/out/.gitkeep'
    )

    return $allowedTrackedTmpPaths -contains $RelativePath
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

$resolvedRepoPath = Resolve-RepoRoot -RequestedRepoPath $RepoPath
Set-Location $resolvedRepoPath

$forbiddenPatterns = @(
    'secrets/**',
    '.tmp/**',
    'tmp/**'
)

$trackedForbidden = Get-TrackedMatches -RepoRoot $resolvedRepoPath -Patterns $forbiddenPatterns |
    Where-Object {
        if ($_ -notlike 'tmp/*') {
            return $true
        }

        return -not (Test-PathAllowedInTmp -RelativePath $_)
    }

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

$publicDbStagedAny = git diff --cached --name-only -- 'data/public/public.sqlite3'
if ($publicDbStagedAny) {
    Write-Warning 'data/public/public.sqlite3 is staged. Verify this is intentional before pushing.'
}

$workingTreeChanges = git status --porcelain
if (-not $AutoCommit) {
    git status -sb
    if ($workingTreeChanges) {
        throw "Auto-commit is disabled by default. Commit manually, or re-run with -AutoCommit -Message '<message>'."
    }

    Write-Host '[INFO] Working tree is clean. Running git push for existing local commits.' -ForegroundColor Cyan
    git push
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Message)) {
    throw 'Commit message is required when -AutoCommit is set. Use -Message "your commit message".'
}

git add -A -- . ':(exclude)src/tatemono_map.egg-info/**' ':(exclude)tmp/**' ':(exclude)dist/**'

$stagedChanges = git diff --cached --name-status
if (-not $stagedChanges) {
    Write-Host '[INFO] No commitable changes after excluding generated paths (src/tatemono_map.egg-info/, tmp/, dist/).' -ForegroundColor Yellow
    exit 0
}

Write-Host '[INFO] The following files will be committed:' -ForegroundColor Cyan
$stagedChanges | ForEach-Object { Write-Host "  $_" }

$publicDbStaged = git diff --cached --name-only -- 'data/public/public.sqlite3'
if ($publicDbStaged) {
    Write-Warning 'data/public/public.sqlite3 is staged. Verify this is intentional before pushing.'
}

git commit -m $Message
git push
