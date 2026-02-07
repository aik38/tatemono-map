[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [string]$RepoPath = (Join-Path $env:USERPROFILE "tatemono-map"),
    [int]$MaxItems = 200,
    [int]$Port = 8080,
    [switch]$NoServe
)

$ErrorActionPreference = "Stop"

function Resolve-RepoPath {
    param([string]$RequestedPath)

    if ([string]::IsNullOrWhiteSpace($RequestedPath)) {
        throw "RepoPath が空です。次のアクション: -RepoPath を指定するか、`$env:USERPROFILE\\tatemono-map に clone してください。"
    }

    $resolved = Resolve-Path -Path $RequestedPath -ErrorAction SilentlyContinue
    if (-not $resolved) {
        throw "RepoPath が見つかりません: $RequestedPath`n次のアクション: `$env:USERPROFILE\\tatemono-map に clone するか、正しい -RepoPath を指定してください。"
    }

    $fullPath = $resolved.Path
    if ($fullPath -match "\\OneDrive\\") {
        Write-Warning "OneDrive 配下のリポジトリは非推奨です: $fullPath"
        throw "統一運用のため `$env:USERPROFILE\\tatemono-map を使用してください（OneDrive 配下では実行しません）。"
    }

    if (-not (Test-Path (Join-Path $fullPath ".git"))) {
        throw "Git リポジトリではありません: $fullPath`n次のアクション: tatemono-map の clone 先を指定してください。"
    }

    return $fullPath
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
    throw "-Url が空です。次のアクション: ブラウザで開ける ULUCKS smartlink URL を指定して再実行してください。例: pwsh -File scripts/run_ulucks_smartlink.ps1 -Url 'https://ulucks.example/smartlink/?link_id=YOUR_LINK_ID&mail=user%40example.com'"
}

if (($Url -notmatch "[?&]link_id=") -or ($Url -notmatch "[?&]mail=")) {
    throw "-Url の形式が不正です。`n次のアクション: link_id と mail を含む smartlink URL を単一引用符で指定してください。`n例: -Url 'https://ulucks.example/smartlink/?link_id=YOUR_LINK_ID&mail=user%40example.com'"
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

    if (-not $env:SQLITE_DB_PATH) {
        $env:SQLITE_DB_PATH = "data\tatemono_map.sqlite3"
        Write-Host "[run_ulucks] SQLITE_DB_PATH=$($env:SQLITE_DB_PATH)" -ForegroundColor DarkGray
    }

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
