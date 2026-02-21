# tatemono-map

`tatemono-map` は、建物レジストリを更新し、`data/public/public.sqlite3` から静的サイト (`dist/`) を生成して公開するためのリポジトリです。

## Canonical Registry Workflow (Supported)

このプロジェクトで **サポートする正規ルートは canonical registry のみ** です。  
週次で `buildings_master.csv` を再生成・編集して運用する方式はサポート対象外です。

### One-time seed（初回のみ）

UI でレビュー済みの初期CSVを canonical registry に投入します。

- スクリプト: `scripts/seed_buildings_from_ui.ps1`
- 入力CSV: `tmp/manual/inputs/buildings_seed_ui.csv`
- 例:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 `
  -DbPath data\tatemono_map.sqlite3 `
  -CsvPath tmp\manual\inputs\buildings_seed_ui.csv
```

### Weekly update（週次運用）

週次運用は次の **1コマンドのみ** を使います。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1
```

`weekly_update.ps1` は次を順に実行します。
1. `scripts/run_pdf_zip_latest.ps1`
2. `scripts/ingest_master_import.ps1`
3. `scripts/publish_public.ps1`
4. `python -m tatemono_map.render.build --db-path data/public/public.sqlite3 --output-dir dist --version all`

> `data/public/public.sqlite3` を開いたままだと lock で失敗するため、DB Viewer 等を閉じてから実行してください。

## Legacy buildings_master pipeline (Deprecated)

旧 `buildings_master` 再生成系フローは削除せず `legacy` として隔離しています。  
必要時のみ利用し、通常運用では使わないでください。

- Runbook: [`docs/legacy/runbook_buildings_master.md`](docs/legacy/runbook_buildings_master.md)
- Scripts: `scripts/legacy/`

## ドキュメント

- 運用手順（正本）: [`docs/runbook.md`](docs/runbook.md)
- legacy 手順: [`docs/legacy/runbook_buildings_master.md`](docs/legacy/runbook_buildings_master.md)
- 仕様: [`docs/spec.md`](docs/spec.md)
