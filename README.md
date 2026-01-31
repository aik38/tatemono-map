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

### 1) リポジトリを取得
```powershell
mkdir C:\dev ; cd C:\dev
git clone https://github.com/<your-org>/tatemono-map.git
cd .\tatemono-map
```

### 2) venv 作成・有効化
```powershell
py -3.11 -m venv .venv
. .\.venv\Scripts\Activate.ps1
```

### 3) 依存インストール
```powershell
python -m pip install -U pip
pip install -r requirements.txt
pip install -e .
```

### 4) 起動（API）
```powershell
uvicorn tatemono_map.api.main:app --reload --host 127.0.0.1 --port 8000
```

### 5) 動作確認（/health など）
別ターミナルで実行：
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```
期待されるレスポンス：
```json
{"status": "ok", "app": "Tatemono Map", "time": "2024-01-01T00:00:00+00:00"}
```

ブラウザ確認：
- http://127.0.0.1:8000/
- http://127.0.0.1:8000/b/demo

---

## .env / secrets の扱い（重要）
- **secrets/.env はコミットしない**でください。
- 推奨：`.env.example` を作り、**安全な値だけ**をサンプルとして共有します。
- 実運用の `.env` は **ローカルだけ**に保存してください。

---

## よくある詰まり（FAQ）

### Q1. `fatal: not a git repository`
**原因**：リポジトリ直下にいない。
**対処**：`cd` で `tatemono-map` 直下へ移動してから再実行。
```powershell
cd C:\dev\tatemono-map
git status
```

### Q2. `Address already in use`（ポート競合）
**原因**：8000番ポートが他プロセスで使用中。
**対処**：空いているポートで起動。
```powershell
uvicorn tatemono_map.api.main:app --reload --host 127.0.0.1 --port 8010
```

### Q3. `Activate.ps1` で venv が有効化できない
**原因**：PowerShell の実行ポリシー。
**対処**：現在のユーザーだけ許可して再実行。
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
. .\.venv\Scripts\Activate.ps1
```

### Q4. `ModuleNotFoundError` / `No module named ...`
**原因**：依存インストール漏れ、または venv 未有効化。
**対処**：venv を有効化して再インストール。
```powershell
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

### Q5. `ERR_CONNECTION_REFUSED`（ブラウザで接続不可）
**原因**：API が起動していない、またはポートが異なる。
**対処**：起動コマンドとポートを再確認。
```powershell
uvicorn tatemono_map.api.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 仕様・ドキュメント
- `docs/spec.md`
- `docs/data_contract.md`
- `docs/runbook.md`

---

## 一発 PowerShell コマンド集（README 末尾）

### 1) 日常更新：pull → 変更確認 → add → commit → push
```powershell
git pull
; git status
; git add -A
; git commit -m "chore: update"
; git push
```

### 2) PR運用：feature ブランチ作成 → push → PR → mainへマージ → pull
```powershell
$branch = "feature/your-topic"
; git checkout -b $branch
; git push -u origin $branch
; # PR を作成（GitHub などのUIで）
; # PR を main にマージ
; git checkout main
; git pull
```

### 3) 起動：uvicorn 実行（必要なら --reload / host / port）
```powershell
uvicorn tatemono_map.api.main:app --reload --host 127.0.0.1 --port 8000
```
