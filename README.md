# Tatemono Map（建物/不動産データAPI MVP）

**目的**：建物/不動産データを扱うAPI MVP「tatemono-map」を、**Windows 11 + PowerShell 7.x** だけでローカル起動・運用できるようにするための手順書です。

---

## 前提（必須）
- OS：**Windows 11**
- シェル：**PowerShell 7.x**
- Python：**3.11 以上**（`py -0` で確認）
- Git：インストール済み（`git --version`）

> **OneDrive 外で開発すること**
> - **理由**：OneDrive の同期/ロックが仮想環境や `.venv` の作成・更新を不安定にするためです。
> - 例：`C:\dev\tatemono-map` に clone し、Desktop には **ショートカットだけ**置く運用を推奨します。

---

## 初回セットアップ（Windows + PowerShell 完結）
以下は **PowerShell にコピペ実行**できます（改行/`;` どちらでも可）。

### 1) リポジトリを取得（未クローンの場合）
> まずは任意の場所に clone してください。例：
> `git clone https://github.com/<your-org>/tatemono-map.git C:\dev\tatemono-map`

### 2) リポジトリ直下へ移動（プロンプトが `PS ...\tatemono-map>` になる状態）
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

# どこに居ても repo 直下へ移動できているか確認
$PWD
```

### 3) venv 作成・有効化（ブロック単体で成立）
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

if (-not (Test-Path .\.venv)) { py -m venv .venv }
. .\.venv\Scripts\Activate.ps1
```

### 4) 依存インストール（ブロック単体で成立）
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

. .\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r .\requirements.txt
python -m pip install -e .
```

#### 依存関係を追加するとき（MVP拡張時）
- **requirements.txt 管理の場合**：追加したいパッケージ名を `requirements.txt` に追記してから再インストール。
- **pyproject.toml 管理の場合**：`[project] dependencies = [...]` に追記して `pip install -e .` を再実行。
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

. .\.venv\Scripts\Activate.ps1
# 例：requirements.txt を更新した場合
python -m pip install -r .\requirements.txt
```

### 5) 起動（API）
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

. .\.venv\Scripts\Activate.ps1
New-Item -ItemType Directory -Force (Join-Path $REPO "data") | Out-Null
$env:SQLITE_DB_PATH = (Join-Path $REPO "data\tatemono_map.sqlite3")
python -m uvicorn tatemono_map.api.main:app --reload --host 127.0.0.1 --port 8000
```

### 6) 動作確認（/health など）
別ターミナルで実行：
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

Invoke-RestMethod http://127.0.0.1:8000/health
```
期待されるレスポンス：
```json
{"status": "ok", "app": "Tatemono Map", "time": "2024-01-01T00:00:00+00:00"}
```

ブラウザ確認：
- http://127.0.0.1:8000/
- http://127.0.0.1:8000/b/demo

#### /buildings の作成・取得（PowerShell 例）
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

# 作成（POST）
$body = @{
  name = "サンプルビル"
  address = "東京都千代田区1-1-1"
  lat = 35.681236
  lng = 139.767125
  building_type = "office"
  floors = 10
  year_built = 1999
  source = "manual"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/buildings `
  -ContentType "application/json" -Body $body

# 取得（GET）
Invoke-RestMethod http://127.0.0.1:8000/buildings
```

---

## .env / secrets の扱い（重要）
- **secrets/.env はコミットしない**でください。
- 推奨：`.env.example` を作り、**安全な値だけ**をサンプルとして共有します。
- 実運用の `.env` は **ローカルだけ**に保存してください。
- **SQLITE_DB_PATH**：SQLite のファイルパスを指定（未指定なら `./data/tatemono_map.sqlite3`）。PowerShell での設定例は下記の起動手順を参照。
- **.env.example**：`DATABASE_URL` などの接続先や通知系のキーを記載した雛形です。実運用値は `.env` にのみ保存します。

---

## よくある詰まり（FAQ）

### Q1. `fatal: not a git repository`
**原因**：リポジトリ直下にいない（プロンプトが `PS ...\tatemono-map>` になっていない）。
**対処**：ブロック冒頭の repo 移動スクリプトを実行してから再実行。
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

git status
```

### Q2. `Address already in use`（ポート競合）
**原因**：8000番ポートが他プロセスで使用中。
**対処**：空いているポートで起動。
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

. .\.venv\Scripts\Activate.ps1
$env:SQLITE_DB_PATH = (Join-Path $REPO "data\tatemono_map.sqlite3")
python -m uvicorn tatemono_map.api.main:app --reload --host 127.0.0.1 --port 8010
```

### Q3. `Activate.ps1` で venv が有効化できない
**原因**：PowerShell の実行ポリシー。
**対処**：現在のユーザーだけ許可して再実行。
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
. .\.venv\Scripts\Activate.ps1
```

### Q4. `ModuleNotFoundError` / `No module named ...`
**原因**：依存インストール漏れ、または venv 未有効化。
**対処**：venv を有効化して再インストール。
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

. .\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
python -m pip install -e .
```

### Q5. `ERR_CONNECTION_REFUSED`（ブラウザで接続不可）
**原因**：API が起動していない、またはポートが異なる。
**対処**：起動コマンドとポートを再確認。
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

. .\.venv\Scripts\Activate.ps1
$env:SQLITE_DB_PATH = (Join-Path $REPO "data\tatemono_map.sqlite3")
python -m uvicorn tatemono_map.api.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 仕様・ドキュメント
- `docs/spec.md`
- `docs/data_contract.md`
- `docs/runbook.md`

---

## 一発 PowerShell コマンド集（README 末尾）

### 1) repo 直下へ移動 + git status
**⚠️ 注意：`On branch main` などの「出力」はコマンドではないので貼り付けない**
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

git status
```

### 2) venv 作成 + 依存インストール
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

if (-not (Test-Path .\.venv)) { py -m venv .venv }
. .\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r .\requirements.txt
python -m pip install -e .
```

### 3) SQLITE_DB_PATH セット + uvicorn 起動
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

. .\.venv\Scripts\Activate.ps1
New-Item -ItemType Directory -Force (Join-Path $REPO "data") | Out-Null
$env:SQLITE_DB_PATH = (Join-Path $REPO "data\tatemono_map.sqlite3")
python -m uvicorn tatemono_map.api.main:app --reload --host 127.0.0.1 --port 8000
```

### 4) 別ターミナルで health / CRUD 例
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

Invoke-RestMethod http://127.0.0.1:8000/health
```

### 5) pytest 実行（pytest が無い環境でも動く）
```powershell
$ErrorActionPreference = "Stop"
$REPO = (git rev-parse --show-toplevel 2>$null)
if (-not $REPO) { $REPO = Join-Path $env:USERPROFILE "tatemono-map" }
if (-not (Test-Path (Join-Path $REPO ".git"))) { throw "Not a git repository: $REPO" }
Set-Location $REPO

. .\.venv\Scripts\Activate.ps1
python -m pip install pytest
python -m pytest
```
