[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [string]$RepoPath,
    [int]$MaxItems = 200,
    [int]$Port = 8080,
    [switch]$NoServe
)

$ErrorActionPreference = "Stop"

function Resolve-RepoPath {
    param([string]$RequestedPath)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $candidates += $RequestedPath
    } else {
        $candidates += "C:\dev\tatemono-map"
        if ($env:USERPROFILE) {
            $candidates += (Join-Path $env:USERPROFILE "tatemono-map")
            $candidates += (Join-Path $env:USERPROFILE "OneDrive\Desktop\tatemono-map")
        }
    }

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        $resolved = Resolve-Path -Path $candidate -ErrorAction SilentlyContinue
        if (-not $resolved) { continue }

        $fullPath = $resolved.Path
        if (Test-Path (Join-Path $fullPath ".git")) {
            return $fullPath
        }
    }

    $tips = @(
        "RepoPath が見つかりません。候補を確認してください:",
        " - C:\dev\tatemono-map",
        " - `$env:USERPROFILE\tatemono-map",
        " - `$env:USERPROFILE\OneDrive\Desktop\tatemono-map"
    )
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $tips += "指定された -RepoPath: $RequestedPath"
    }
    $tips += "次のアクション: 正しいパスを -RepoPath で明示するか、上記候補に clone してください。"
    throw ($tips -join [Environment]::NewLine)
}

function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Action
    )
    Write-Host "[run_ulucks] $Label" -ForegroundColor Cyan
    & $Action
}

if ([string]::IsNullOrWhiteSpace($Url)) {
    throw "-Url が空です。次のアクション: ブラウザで開ける ULUCKS smartlink URL を指定して再実行してください。例: pwsh -File scripts/run_ulucks_smartlink.ps1 -Url \"https://...\""
}

$resolvedRepoPath = Resolve-RepoPath -RequestedPath $RepoPath

if ($PSCmdlet.ShouldProcess($resolvedRepoPath, "Run smartlink ingest + normalize + build")) {
    Set-Location $resolvedRepoPath
    Write-Host "[run_ulucks] Repo: $resolvedRepoPath" -ForegroundColor DarkGray

    Invoke-Step "git pull --ff-only" {
        git pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            throw "git pull --ff-only に失敗しました。次のアクション: 現在ブランチの競合/未コミット変更を解消して再実行してください。"
        }
    }

    $venvPath = Join-Path $resolvedRepoPath ".venv"
    if (-not (Test-Path $venvPath)) {
        Invoke-Step "python -m venv .venv" {
            python -m venv $venvPath
            if ($LASTEXITCODE -ne 0) {
                throw ".venv 作成に失敗しました。次のアクション: python コマンドが使えるか確認して再実行してください。"
            }
        }
    }

    $activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
    if (-not (Test-Path $activateScript)) {
        throw "Activate スクリプトが見つかりません: $activateScript`n次のアクション: .venv を削除して再実行してください。"
    }
    . $activateScript

    Invoke-Step "python -m pip install -U pip" {
        python -m pip install -U pip
        if ($LASTEXITCODE -ne 0) {
            throw "pip 更新に失敗しました。ネットワーク/プロキシ設定を確認して再実行してください。"
        }
    }

    $requirementsPath = Join-Path $resolvedRepoPath "requirements.txt"
    if (Test-Path $requirementsPath) {
        Invoke-Step "python -m pip install -r requirements.txt" {
            python -m pip install -r $requirementsPath
            if ($LASTEXITCODE -ne 0) {
                throw "requirements.txt のインストールに失敗しました。次のアクション: requirements.txt の依存解決を確認してください。"
            }
        }
    } else {
        Invoke-Step "python -m pip install -e ." {
            python -m pip install -e .
            if ($LASTEXITCODE -ne 0) {
                throw "editable install に失敗しました。次のアクション: pyproject.toml を確認して再実行してください。"
            }
        }
    }

    try {
        Invoke-Step "ingest smartlink (--max-items $MaxItems)" {
            python -m tatemono_map.ingest.ulucks_smartlink --url $Url --max-items $MaxItems --fail
            if ($LASTEXITCODE -ne 0) {
                throw "ingest failed"
            }
        }
    } catch {
        throw "ingest に失敗しました。`n原因候補: smartlink の有効期限切れ / URL不正 / 取り込み件数0件。`n次のアクション: URLをブラウザで開いて一覧が見えるか確認し、必要なら smartlink を再生成してください。`n詳細: $($_.Exception.Message)"
    }

    Invoke-Step "normalize building summaries" {
        python scripts/normalize_building_summaries.py
        if ($LASTEXITCODE -ne 0) {
            throw "normalize_building_summaries.py が失敗しました。次のアクション: DB内容を確認して再実行してください。"
        }
    }

    Invoke-Step "build dist" {
        python -m tatemono_map.render.build --output-dir dist
        if ($LASTEXITCODE -ne 0) {
            throw "build に失敗しました。次のアクション: 禁止情報混入エラーや DB 必須項目の欠損を確認してください。"
        }
    }

    $indexPath = Join-Path $resolvedRepoPath "dist\index.html"
    if (-not (Test-Path $indexPath)) {
        throw "dist/index.html が生成されていません。次のアクション: build ログを確認し、失敗原因を解消して再実行してください。"
    }

    if ($NoServe) {
        Write-Host "[run_ulucks] Open file://$indexPath" -ForegroundColor Green
        Start-Process $indexPath | Out-Null
        Write-Host "[run_ulucks] done (NoServe)" -ForegroundColor Green
    } else {
        $urlToOpen = "http://127.0.0.1:$Port/index.html"
        Write-Host "[run_ulucks] Start local server: $urlToOpen" -ForegroundColor Green
        Start-Process $urlToOpen | Out-Null
        python -m http.server $Port --directory dist
    }
}
