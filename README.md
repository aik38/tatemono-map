# tatemono-map

## 1) What is this
`tatemono-map` は、**建物DB（`building_summaries`）から静的Web（`dist/`）を生成し、GitHub Pages で公開するためのMVP**です。

- フローは `DB → dist生成 → 公開`。
- 各物件ページには、住所（`address`）から作る Google Maps 導線を出します（`src/tatemono_map/render/build.py` の `maps_url` 生成）。
- 公開物（`dist/`）には、**号室 / 参照元URL / 管理会社 / 電話などの非公開情報を含めない**ことが絶対条件です。
  - `python -m tatemono_map.render.build` は `dist` 生成後に禁止パターン検査を行い、違反時は失敗します。

---

## 2) Quickstart（最短で dist を作って開く）
PowerShell で、まず repo パスを固定してください。

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"   # 例: C:\Users\OWNER\tatemono-map
```

> 以降のコマンドは **どのCWDからでも** 動くように `-File "$REPO\..."` / `-RepoPath $REPO` を付けています。

### セットアップ
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\setup.ps1" -RepoPath $REPO
```

### dist 生成（MVP本線）
```powershell
python -m tatemono_map.render.build --db-path "$REPO\data\public\public.sqlite3" --output-dir "$REPO\dist" --version all
```

### 表示確認
```powershell
Start-Process "$REPO\dist\index.html"
```

---

## 3) Daily ops（一次資料→CSV→合算）
手動一次資料（PDF ZIP / 保存HTML）の運用手順は `docs/runbook.md` を正本にしています。

- 入口のみ（詳細は runbook 参照）:
  - `scripts/run_pdf_zip_latest.ps1`
  - `scripts/run_mansion_review_html.ps1`
  - `scripts/run_merge_building_masters.ps1`

---

## 4) Git sync / push（CWD非依存）

### 推奨（ラッパー）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\sync.ps1" -RepoPath $REPO
```

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\push.ps1" -RepoPath $REPO -Message "docs: update README" -SensitiveColumnPolicy strict
```

### 生 git の代替（pullのみ）
```powershell
git -C $REPO pull --ff-only
```

> `push.ps1` は push 前に安全ガードを実行し、`secrets/**`, `.tmp/**`, `tmp/**`（例外: `.gitkeep`, `tmp/manual/README.md`）や root `*.csv` の tracked 混入を検知すると停止します。

---

## 5) Troubleshooting

### A. RepoPath を間違えている（例: `C:\Users\AI\tatemono-map`）
症状:
- `Repository path not found`
- `Not a git repository`
- `pyproject.toml not found`

対処:
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Test-Path "$REPO\.git"
Test-Path "$REPO\pyproject.toml"
```
両方 `True` になってから再実行してください。

### B. `Forbidden tracked files detected` が出る
意味:
- `tmp/**` などに **追跡されるべきでない生成物**（CSV/zip/html など）が混入しています。

確認:
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\git_doctor.ps1" -RepoPath $REPO
```

基本対応:
```powershell
git -C $REPO rm --cached <対象パス>
```
例（tmp 配下をまとめて除外する場合）:
```powershell
git -C $REPO rm --cached -r tmp
```

運用方針:
- `tmp/manual/README.md` と `.gitkeep` は追跡可。
- それ以外の `tmp/**` 生成物は追跡NG。

---

## 正本ドキュメント
- 運用の正本: [`docs/runbook.md`](docs/runbook.md)
- 仕様の正本: [`docs/spec.md`](docs/spec.md)
- 工程の正本: [`docs/wbs.md`](docs/wbs.md)
