# runbook（運用手順）

現行運用は **初回 seed + 週次 1 コマンド更新** です。  
旧来のマスター再構築フローは **現行運用では使用しません**。

## 1) 初回セットアップ（setup）

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -RepoPath .
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -RepoPath .
```

## 2) 初回 seed（buildings投入）

手動確認済み CSV を canonical DB（`buildings`）へ投入します。

### 入力ファイル
- `tmp/manual/inputs/buildings_seed_ui.csv`

### 実行コマンド
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 `
  -DbPath .\data\tatemono_map.sqlite3 `
  -CsvPath .\tmp\manual\inputs\buildings_seed_ui.csv
```

### 期待される挙動
- 既存建物を再利用し、重複追加を避ける（idempotent / 冪等）。
- `canonical_name` / `canonical_address` は自動上書きしない。

## 3) 週次1コマンド（weekly_update）

### 入力 ZIP の置き場・命名規則（推奨）
- 置き場: `tmp/manual/inputs/pdf_zips/`
- 命名: `リアプロ-*.zip` / `ウラックス-*.zip`
- ZIP はローカル入力物として扱い、コミットしない（`.gitignore`）。

### 実行コマンド（推奨）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 -RepoPath . -DbPath .\data\tatemono_map.sqlite3 -DownloadsDir .\tmp\manual\inputs\pdf_zips -QcMode warn
```

### ZIP 処理を飛ばす場合（`master_import.csv` 直指定）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 -RepoPath . -DbPath .\data\tatemono_map.sqlite3 -MasterImportCsv <outdir>\master_import.csv
```

### 実行内容（scripts準拠）
1. PDF バッチ処理（`run_pdf_zip_latest.ps1` → `run_pdf_zip.ps1`）
2. `master_import.csv` ingest（listings 更新 + 建物突合）
3. review CSV 出力（`tmp/review/`）
4. `publish_public` 実行（`data/public/public.sqlite3` 更新）
5. `render.build` 実行（`dist/` 更新。入力は `data/public/public.sqlite3` で Pages CI と同じ）

> 注: 週次運用は `buildings` テーブルを再構築しません。既存 canonical を維持しつつ、新規建物のみ追加します。

### review CSV の意味（`tmp/review/`）
- `suspects_*.csv`
  - 候補はあるが確信不足（僅差・競合・閾値不足）。人手判断で統合先を決める。
- `unmatched_listings_*.csv`
  - `building_id` が確定できなかった listing。住所揺れ・建物名揺れ・入力欠損の切り分け対象。
- `new_buildings_*.csv`
  - 自動で新規追加した建物の確認用。誤追加がないか点検し、必要に応じて alias/seed で統合。

#### 推奨トリアージ順
1. `suspects`
2. `unmatched_listings`
3. `new_buildings`

## 4) 公開反映（GitHub Pages）

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\publish_public.ps1 -RepoPath .
```

- push 対象は原則 `data/public/public.sqlite3`（必要なら周辺メタ）。
- `dist/` は `.gitignore` 対象のビルド成果物。
- GitHub Pages 本番は CI（`.github/workflows/pages.yml`）が `data/public/public.sqlite3` から `dist/` を生成してデプロイする。

`git add data/public/public.sqlite3` で ignored と表示された場合:

```powershell
git check-ignore -v data/public/public.sqlite3
```

- 追跡済みなら通常 commit できる。
- 未追跡でどうしても追加できない場合のみ `git add -f data/public/public.sqlite3` を最終手段として使う（通常は不要）。

## 再現性チェックリスト（週次実行後）

```powershell
sqlite3 data/tatemono_map.sqlite3 "select count(*) from listings;"
sqlite3 data/tatemono_map.sqlite3 "select count(*) from building_summaries;"
sqlite3 data/public/public.sqlite3 "select count(*) from building_summaries;"
Get-Item data/public/public.sqlite3 | Format-List Length,LastWriteTime
```

## トラブルシュート

- `weekly_update` が `rows=0` で停止する:
  - 安全停止（新しい入力なし）。`tmp/manual/inputs/pdf_zips/` の ZIP 配置と `リアプロ-*.zip` / `ウラックス-*.zip` のファイル名を確認する。
- `weekly_update` が `master_import` header mismatch で停止する:
  - `tmp/pdf_pipeline/out/<timestamp>/master_import.csv` の先頭ヘッダ行と行数ログを確認する（`run_pdf_zip.ps1` が `[OK] master_import_header=...` と `[OK] master_import_rows=...` を出力）。
- `publish_public` がロックで失敗する:
  - 事前ロック確認（ReadWrite + Share None）で弾かれる場合あり。
  - 内部では `public.sqlite3.tmp` を作成し、SQLite connection close 後に `os.replace(tmp_db, public_db)` で置換する。
  - 置換時に WinError 32 が続く場合は lock diagnostics（`tmp_db/public_db` の状態）を出力して停止する。

### ロック時の復旧（短縮版）
- DB Browser for SQLite を閉じる。
- VSCode の SQLite 拡張で `public.sqlite3` を開いているタブを閉じる。
- Explorer のプレビュー（詳細ウィンドウ含む）を閉じる。
- 数秒待ってから `scripts/publish_public.ps1` を再実行する。

## テスト（推奨手順）

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q tests
```
