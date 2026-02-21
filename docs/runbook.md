# Runbook（Canonical Registry / Supported）

## 0. 目的

本 runbook は **canonical buildings registry を正ルートとして運用する手順**のみを扱います。  
`buildings_master` 再生成系は legacy 扱いで、通常運用には使用しません。

- legacy 手順: [`docs/legacy/runbook_buildings_master.md`](legacy/runbook_buildings_master.md)

## 1. 前提

- PowerShell 7 を使用
- リポジトリルートで実行（または絶対パス指定）
- `data/public/public.sqlite3` を DB Viewer などで開いたままにしない（lock 回避）

## 2. One-time seed（初回のみ）

`buildings` テーブルを初期化するため、UIレビュー済みCSVを投入します。

- スクリプト: `scripts/seed_buildings_from_ui.ps1`
- 入力: `tmp/manual/inputs/buildings_seed_ui.csv`

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 `
  -DbPath data\tatemono_map.sqlite3 `
  -CsvPath tmp\manual\inputs\buildings_seed_ui.csv
```

## 3. Weekly update（唯一の正規コマンド）

週次更新は次の1コマンドを実行します。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1
```

`weekly_update.ps1` は以下を順番に実行します。
1. `scripts/run_pdf_zip_latest.ps1`
2. `scripts/ingest_master_import.ps1`
3. `scripts/publish_public.ps1`
4. `python -m tatemono_map.render.build --db-path data/public/public.sqlite3 --output-dir dist --version all`

## 4. 成果物

- 公開DB: `data/public/public.sqlite3`
- 静的サイト: `dist/`
- 週次取り込みの入力: `tmp/pdf_pipeline/out/<timestamp>/master_import.csv`
- レビュー用出力（必要時）: `tmp/manual/review/*.csv`

## 5. 運用ポリシー

- `canonical_name` / `canonical_address` は自動上書きしない
- 週次処理で判定不能な候補は review CSV に逃がし、処理は継続する
- `buildings_master.csv` を「正本」として編集・再生成する運用は行わない
