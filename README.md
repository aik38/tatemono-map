# Tatemono Map（建物/不動産データAPI MVP）

**目的**：建物/不動産データを扱うAPI MVP「tatemono-map」を、**Windows 11 + PowerShell 7.x** だけでローカル起動・運用できるようにするための手順書です。

---

## 一発起動（repo外からOK）
**最短ワンライナー：**
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\dev.ps1"
```

**repoパスを指定して実行（repo外からOK）：**
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\dev.ps1" -RepoPath "C:\dev\tatemono-map"
```

> **⚠️ 注意**：`git` の **出力（On branch main など）をコピペして実行しない**でください。出力はコマンドではありません。

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
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\dev\tatemono-map\scripts\dev.ps1" -RepoPath "C:\dev\tatemono-map"
```

---

## Git運用の土台（Codex→merge→ローカルsync→開発→push）
1. **Codex / GitHub で変更 → PR → merge（main）**
2. **ローカル同期**：`scripts/sync.ps1` で **fast-forward のみ**同期
3. **開発/実行**：`scripts/dev.ps1` で起動・検証
4. **コミット & push**：`scripts/push.ps1` で一発 push

> **ローカルは必ず `sync.ps1` で追従**し、`git pull` を手で打ち散らかさない運用に揃えます。

---

## スクリプト一覧（PowerShell）
### 1) 開発・起動（`scripts/dev.ps1`）
- **repo直下へ移動** → **venv 作成/有効化** → **依存インストール** → **DBパス設定** → **uvicorn起動**
- オプション：`-InstallPytest` / `-RunTests` / `-NoReload`

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\dev\tatemono-map\scripts\dev.ps1" -RepoPath "C:\dev\tatemono-map" -ListenHost 127.0.0.1 -Port 8000
```

### 2) ローカル同期（`scripts/sync.ps1`）
- **未コミットがあれば停止**（`-Force` で無視可能）
- `git pull --ff-only`
- オプション：`-RunTests`

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\dev\tatemono-map\scripts\sync.ps1" -RepoPath "C:\dev\tatemono-map"
```

### 3) コミット & push（`scripts/push.ps1`）
- `git add -A` → `git commit -m "..."` → `git push origin main`
- **commit message は必須**

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\dev\tatemono-map\scripts\push.ps1" -RepoPath "C:\dev\tatemono-map" -Message "feat: add building import"
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
**原因**：リポジトリ直下にいない。
**対処**：`scripts/dev.ps1` / `scripts/sync.ps1` / `scripts/push.ps1` に `-RepoPath` を指定して実行。

### Q2. `Address already in use`（ポート競合）
**原因**：8000番ポートが他プロセスで使用中。
**対処**：`-Port` を変えて起動。
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\dev\tatemono-map\scripts\dev.ps1" -RepoPath "C:\dev\tatemono-map" -Port 8010
```

### Q3. `Activate.ps1` で venv が有効化できない
**原因**：PowerShell の実行ポリシー。
**対処**：現在のユーザーだけ許可して再実行。
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
