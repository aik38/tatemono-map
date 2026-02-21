# tatemono-map

## Canonical DB
- 正本（canonical）は `buildings` テーブルのみ。
- `canonical_name` / `canonical_address` は seed と weekly ingest のどちらでも自動上書きしない。

## Seed (UI手修正CSV → DB)
### Input
- `tmp/manual/inputs/buildings_seed_ui.csv`

### Command
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 -DbPath .\data\tatemono_map.sqlite3 -CsvPath .\tmp\manual\inputs\buildings_seed_ui.csv
```

### Output
- `data/tatemono_map.sqlite3`
  - `buildings`: 既存建物は増やさず再利用（idempotent）
  - `building_sources`: evidence と alias を追記/更新

## Weekly update (1コマンド)
### Input
- `tmp/pdf_pipeline/out/<timestamp>/master_import.csv`

### Command
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 -RepoPath . -DbPath .\data\tatemono_map.sqlite3
```

### Internal flow
1. `python -m tatemono_map.cli.pdf_batch_run`
2. `python -m tatemono_map.building_registry.ingest_master_import`
3. `scripts/publish_public.ps1`
4. `python -m tatemono_map.render.build`

### Output
- `data/tatemono_map.sqlite3`: listings ingest + building_id match（canonicalは保護）
- `data/public/public.sqlite3`: 公開DB
- `dist/`: render結果
- `tmp/review/`: review CSV

## Review CSV (`tmp/review/`)
- `new_buildings_*.csv`: 新規建物として追加した行
- `suspects_*.csv`: address一致だが低信頼/競合候補あり
- `unmatched_listings_*.csv`: building_id未解決のlisting

各CSVの主な列:
- `source_kind`, `source_id`, `name`, `address`
- `normalized_name`, `normalized_address`
- `reason`, `candidate_building_ids`, `candidate_scores`
