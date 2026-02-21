# spec

## What this system is
このシステムは、北九州賃貸データ向けの **建物単位 canonical database + 公開配信基盤** です。

- 正本: SQLite `buildings` テーブル
- 取り込み対象: 複数ソースの空室情報（listing）
- 目的: 建物との突合結果を公開 DB / 静的 HTML として継続配信

## Why
- ソースごとの表記ゆれを吸収し、建物単位で一貫した公開情報を提供するため。
- 週次オペレーションを 1 コマンド化し、属人化を減らすため。

## Non-goals
- `buildings_master` の全件再生成を運用フローに戻さない。
- `canonical_name` / `canonical_address` を自動更新しない。

## Canonical rules
- `buildings` が唯一の canonical source of truth。
- seed / weekly ingest は新規建物追加と listing 更新を行う。
- canonical 値の修正は手動判断で行う（自動上書き禁止）。

## Data model overview
- `buildings`
  - canonical 建物情報。
- `listings`
  - ソース由来の募集情報（derived）。
- `building_sources` など
  - aliases / evidence を保持。
- 公開成果物
  - `data/public/public.sqlite3`
  - `dist/`
- review 出力
  - `tmp/review/new_buildings_*.csv`
  - `tmp/review/suspects_*.csv`
  - `tmp/review/unmatched_listings_*.csv`

## Processing flow

```text
Sources -> normalize -> ingest listings -> match -> publish_public -> render.build
                 \-> tmp/review/*.csv (needs review)

Seed CSV -> seed_from_ui -> buildings (canonical, protected)
```

## Operations contract
- 初回投入: `scripts/seed_buildings_from_ui.ps1`
- 週次更新: `scripts/weekly_update.ps1`
- 公開 DB 更新: `scripts/publish_public.ps1`（weekly 内で実行）
- 出力先:
  - `tmp/review/`
  - `data/public/public.sqlite3`
  - `dist/`
