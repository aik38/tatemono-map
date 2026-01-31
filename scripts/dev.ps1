param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE "tatemono-map"),
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$NoReload,
    [switch]$InstallPytest,
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

$venvPath = Join-Path $resolvedRepoPath ".venv"
if (-not (Test-Path $venvPath)) {
    python -m venv $venvPath
}

$activateScript = Join-Path $venvPath "Scripts\\Activate.ps1"
. $activateScript

python -m pip install -U pip
python -m pip install -r (Join-Path $resolvedRepoPath "requirements.txt")

if ($InstallPytest -or $RunTests) {
    python -m pip install pytest
}

if ($RunTests) {
    python -m pytest -q
}

$dbDirectory = Join-Path $resolvedRepoPath "data"
if (-not (Test-Path $dbDirectory)) {
    New-Item -ItemType Directory -Force $dbDirectory | Out-Null
}

$dbPath = Join-Path $dbDirectory "tatemono_map.sqlite3"
$env:SQLITE_DB_PATH = $dbPath

Write-Host "Repo: $resolvedRepoPath"
Write-Host "Venv: $venvPath"
Write-Host "DB: $dbPath"

$uvArgs = @(
    "uvicorn",
    "tatemono_map.api.main:app",
    "--host",
    $ListenHost,
    "--port",
    $Port.ToString()
)

if (-not $NoReload) {
    $uvArgs += "--reload"
}

python -m @uvArgs
