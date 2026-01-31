param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE "tatemono-map"),
    [switch]$Force,
    [switch]$RunTests
)

$ErrorActionPreference = "Stop"

function Resolve-RepoPath {
    param(
        [string]$Path
    )

    $resolvedPath = Resolve-Path -Path $Path -ErrorAction SilentlyContinue
    if (-not $resolvedPath) {
        throw "Repo path not found: $Path"
    }

    $fullPath = $resolvedPath.Path
    if (-not (Test-Path (Join-Path $fullPath ".git"))) {
        throw "Not a git repository: $fullPath"
    }

    return $fullPath
}

$resolvedRepoPath = Resolve-RepoPath -Path $RepoPath
Set-Location $resolvedRepoPath

$gitStatus = git status --porcelain
if ($gitStatus -and -not $Force) {
    throw "Uncommitted changes detected. Commit or stash before syncing, or re-run with -Force."
}

git pull --ff-only

if ($RunTests) {
    $venvPath = Join-Path $resolvedRepoPath ".venv"
    if (Test-Path $venvPath) {
        $activateScript = Join-Path $venvPath "Scripts\\Activate.ps1"
        . $activateScript
    }

    python -m pytest -q
}
