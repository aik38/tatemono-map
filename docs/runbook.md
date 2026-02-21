# runbook

現行の運用は **初回 seed + 週次 1 コマンド更新** です。
旧来の `buildings_master` 再構築系フローは使用しません。

## 0. Prerequisites
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -RepoPath .
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -RepoPath .
```

## 1. Initial seed（初回のみ / 再実行可）
手動確認済み CSV を canonical DB に投入します。

### Input
- `tmp/manual/inputs/buildings_seed_ui.csv`

### Command
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 `
  -DbPath .\data\tatemono_map.sqlite3 `
  -CsvPath .\tmp\manual\inputs\buildings_seed_ui.csv
```

### Expected behavior
- 既存建物を再利用し、重複追加を避ける（idempotent）。
- `canonical_name` / `canonical_address` は自動上書きしない。

## 2. Weekly operation（1 command）

### Command
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 `
  -RepoPath . `
  -DbPath .\data\tatemono_map.sqlite3
```

### What it does
1. PDF バッチ処理を実行
2. `master_import.csv` を ingest して listing 更新 + 建物突合
3. 公開 DB へ反映
4. 静的 HTML を再生成

### Output locations
- `tmp/review/` : レビュー CSV
- `data/public/public.sqlite3` : 公開 DB
- `dist/` : 静的 HTML

## 3. Review CSV interpretation
`tmp/review/` に以下が出ます。

- `new_buildings_*.csv`
  - 新規建物として追加候補/追加済みの確認用。
- `suspects_*.csv`
  - 類似候補はあるが自信度不足・競合あり。
- `unmatched_listings_*.csv`
  - 建物に紐づかなかった listing。

## 4. Correction policy（canonical を守る）
- canonical 値は自動で書き換えない。
- 修正が必要な場合は、手動確認後に seed CSV や alias/evidence 管理で反映する。
- 不一致が残っても weekly パイプラインは継続し、レビュー CSV で後追い対応する。

## 5. Safety / idempotency checklist
- seed を 2 回実行しても建物件数が不自然に増えない。
- weekly を連続実行しても canonical が勝手に変わらない。
- unmatched がある場合は `tmp/review/unmatched_listings_*.csv` が生成される。
