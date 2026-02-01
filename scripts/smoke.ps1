param(
    [string]$RepoPath = (Join-Path $env:USERPROFILE "tatemono-map"),
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$DevSeed,
    [switch]$Debug,
    [int]$HealthTimeoutSec = 60,
    [int]$HealthIntervalSec = 2
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

function Resolve-BooleanFlag {
    param(
        [string]$Name,
        [switch]$Enabled
    )

    if ($Enabled) {
        Set-Item -Path "Env:$Name" -Value "true"
        return $true
    }

    $raw = (Get-Item "Env:$Name" -ErrorAction SilentlyContinue).Value
    if (-not $raw) {
        return $false
    }

    return $raw.ToLowerInvariant() -eq "true"
}

function Test-PortListening {
    param(
        [string]$HostName,
        [int]$TargetPort
    )

    $testCommand = Get-Command -Name Test-NetConnection -ErrorAction SilentlyContinue
    if ($testCommand) {
        return Test-NetConnection -ComputerName $HostName -Port $TargetPort -InformationLevel Quiet
    }

    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect($HostName, $TargetPort)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

function Wait-ForHealth {
    param(
        [string]$Url,
        [int]$TimeoutSec,
        [int]$IntervalSec
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 5
            if ($response) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds $IntervalSec
        }
    }

    return $false
}

function Show-Json {
    param(
        [string]$Url,
        [int]$Depth = 10
    )

    Write-Host ""
    Write-Host "GET $Url"
    $payload = Invoke-RestMethod -Uri $Url
    $payload | ConvertTo-Json -Depth $Depth
}

$resolvedRepoPath = Resolve-RepoPath -Path $RepoPath
Set-Location $resolvedRepoPath

Write-Host "Running git pull --ff-only..."
& git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    throw "git pull --ff-only failed. Resolve git issues and retry."
}

$devSeedEnabled = Resolve-BooleanFlag -Name "DEV_SEED" -Enabled:$DevSeed
$debugEnabled = Resolve-BooleanFlag -Name "DEBUG" -Enabled:$Debug

$baseUrl = "http://$ListenHost`:$Port"

$serverRunning = Test-PortListening -HostName $ListenHost -TargetPort $Port
if (-not $serverRunning) {
    $devScript = Join-Path $resolvedRepoPath "scripts\dev.ps1"
    Write-Host "Starting server: $devScript"
    Start-Process -FilePath "pwsh" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $devScript,
        "-ListenHost",
        $ListenHost,
        "-Port",
        $Port.ToString()
    ) -WorkingDirectory $resolvedRepoPath | Out-Null
} elseif ($DevSeed -or $Debug) {
    Write-Warning "Server already running. DEV_SEED/DEBUG changes require a restart to take effect."
}

$healthUrl = "$baseUrl/health"
Write-Host "Waiting for $healthUrl ..."
$healthy = Wait-ForHealth -Url $healthUrl -TimeoutSec $HealthTimeoutSec -IntervalSec $HealthIntervalSec
if (-not $healthy) {
    throw "Timed out waiting for /health after ${HealthTimeoutSec}s."
}

Show-Json -Url $healthUrl -Depth 6
Show-Json -Url "$baseUrl/buildings?limit=3&offset=0" -Depth 10
Show-Json -Url "$baseUrl/b/demo" -Depth 10

if ($debugEnabled) {
    Show-Json -Url "$baseUrl/debug/db" -Depth 10
} else {
    Write-Host ""
    Write-Host "DEBUG is disabled. Set DEBUG=true or pass -Debug to query /debug/db."
}
