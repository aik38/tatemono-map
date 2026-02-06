# Tatemono Map（建物/不動産データAPI MVP）

**目的**：建物/不動産データを扱うAPI MVP「tatemono-map」を、**Windows 11 + PowerShell 7.x** だけでローカル起動・運用できるようにするための手順書です。

---

## 最短ルート（迷ったらここだけ）
**1本の流れで迷わない運用手順です。GitHub で merge した後の同期もこれだけ。**

0) **前提：PowerShell 7.x / Windows 11**

1) **同期（GitHub→ローカル）**
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Set-Location $REPO
git pull --ff-only
git status
```

2) **起動（scripts/dev.ps1）**
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev.ps1"
```

3) **ローカル疎通確認（scripts/smoke.ps1）**
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\smoke.ps1"
```

3.5) **静的HTML生成（build）**
```powershell
python -m tatemono_map.render.build --output-dir dist
```

4) **変更の取り込み（コミット&push）**
- `scripts/push.ps1` で一発 push（詳細は下記の「スクリプト一覧」）

5) **よくある停止理由（sync.ps1が止まる）**
- “Untracked files: db/ や dist_tmp などがあると sync.ps1 が止まる”
  - **対処（1行）**：`db/` と `dist_tmp` 系を `.gitignore` に入れる（推奨） or `sync.ps1 -Force`（不要なら削除）
  - `tmp_ulucks_*.html` は smartlink デバッグ生成物のためコミット不要です（`dist_tmp/` など Git 管理外に出力）。

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

## 初回セットアップ
### 1) リポジトリを取得（未クローンの場合）
```powershell
git clone https://github.com/<your-org>/tatemono-map.git C:\dev\tatemono-map
```

### 2) 依存インストール & 起動
初回以降は **`scripts/dev.ps1` だけでOK** です。
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\dev.ps1"
```

---

## Git運用の土台（Codex→merge→ローカルsync→開発→push）
1. **Codex / GitHub で変更 → PR → merge（main）**
2. **ローカル同期**：`scripts/sync.ps1` で **fast-forward のみ**同期
3. **開発/実行**：`scripts/dev.ps1` で起動・検証
4. **コミット & push**：`scripts/push.ps1` で一発 push

---

## スクリプト一覧（PowerShell）
### 1) 開発・起動（`scripts/dev.ps1`）
- **venv 作成/有効化** → **依存インストール** → **DBパス設定** → **uvicorn起動**
- オプション：`-InstallPytest` / `-RunTests` / `-NoReload`

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\dev.ps1" -ListenHost 127.0.0.1 -Port 8000
```

### 2) ローカル同期（`scripts/sync.ps1`）
- **未コミットがあれば停止**（`-Force` で無視可能）
- `git pull --ff-only`
- オプション：`-RunTests`

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\sync.ps1"
```

### 3) コミット & push（`scripts/push.ps1`）
- `git add -A` → `git commit -m "..."` → `git push origin main`
- **commit message は必須**

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\push.ps1" -Message "feat: add building import"
```

### 4) ローカル疎通確認（`scripts/smoke.ps1`）
- `git pull --ff-only` → サーバ起動確認 → `/health` を待機 → `/health`, `/buildings`, `/b/demo` を叩く
- **DBファイルは環境依存で差分ノイズや容量増の原因になるため Git 管理しません。**
- `DEV_SEED=true`：空DBならデモ1件を投入して `/buildings` が空にならないようにします
- `DEBUG=true`：`/debug/db` を有効化して結果表示します

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\smoke.ps1" -DevSeed -Debug
```

---

## 動作確認（/health など）
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
- **SQLITE_DB_PATH**：SQLite のファイルパスを指定（未指定なら `./data/tatemono_map.sqlite3`）。

---

## 仕様・ドキュメント
- `docs/spec.md`
- `docs/data_contract.md`
- `docs/runbook.md`

---

## FAQ
### Q1. `fatal: not a git repository`
**原因**：誤った場所で `git` を直接実行している。
**対処**：`scripts/dev.ps1` / `scripts/sync.ps1` / `scripts/push.ps1` を使う。

### Q2. `Address already in use`（ポート競合）
**原因**：8000番ポートが他プロセスで使用中。
**対処**：`-Port` を変えて起動。
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\dev.ps1" -Port 8010
```

### Q3. `Activate.ps1` で venv が有効化できない
**原因**：PowerShell の実行ポリシー。
**対処**：現在のユーザーだけ許可して再実行。
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
