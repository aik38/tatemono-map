param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE "tatemono-map"),
    [string]$Message
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

if ([string]::IsNullOrWhiteSpace($Message)) {
    throw "Commit message is required. Use -Message \"your message\"."
}

$resolvedRepoPath = Resolve-RepoPath -Path $RepoPath
Set-Location $resolvedRepoPath

git status

$gitStatus = git status --porcelain
if (-not $gitStatus) {
    throw "No changes to commit."
}

git add -A
git commit -m $Message
git push origin main
