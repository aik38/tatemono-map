# Legacy Runbook: buildings_master pipeline（Deprecated）

> ⚠️ この手順は旧運用です。通常は使用せず、`scripts/weekly_update.ps1` による canonical registry 運用を使ってください。

## 概要

旧運用では、一次資料から `buildings_master.csv` を再生成し、人手補正を反映していました。
このルートは互換のため保持しますが、正規運用ではありません。

## Legacy scripts

- `scripts/legacy/run_buildings_master_from_sources.ps1`
- `scripts/legacy/run_merge_building_masters.ps1`
- `scripts/legacy/buildings_master_from_primary_listings.py`
- `scripts/legacy/buildings_master_from_mr_chintai.py`
- `scripts/legacy/merge_building_masters_primary_wins.py`

## 典型フロー（参考）

1. `tmp/pdf_pipeline/out/<timestamp>/master_import.csv` を用意
2. `tmp/manual/outputs/mansion_review/combined/mansion_review_master_UNIQ_*.csv` を用意
3. `run_buildings_master_from_sources.ps1` で `tmp/manual/outputs/buildings_master/<timestamp>/...` を生成
4. `buildings_master_suspects.csv` を見て overrides を編集
5. overrides 指定で再実行し `buildings_master.csv` を確定

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\legacy\run_buildings_master_from_sources.ps1
```

固定名 primary/secondary を使う旧マージ運用:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\legacy\run_merge_building_masters.ps1
```

## 注意

- 本 legacy フローは将来削除される可能性があります。
- 正規運用への移行先: [`../runbook.md`](../runbook.md)
