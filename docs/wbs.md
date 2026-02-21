# tatemono-map WBS

README/spec/runbook を前提にした運用・改善の工程管理です。

## Phase 0: Canonical-first onboarding fix
- README と docs の入口整備
- canonical ルール（`buildings` 正本 / no auto-overwrite）を明文化
- 週次 1 コマンド運用を標準化

**DoD**
- README から目的・データフロー・実行コマンドが辿れる
- `docs/README.md` で読む順序が明確

## Phase 1: Initial data readiness
- 手動確認済み seed CSV の品質担保
- `seed_buildings_from_ui.ps1` の idempotent 運用確認

**DoD**
- seed 再実行で重複投入が起きない
- canonical 値が自動変更されない

## Phase 2: Weekly update stability
- `weekly_update.ps1` の定常運用
- review CSV を使った未解決データの後追い導線整備

**DoD**
- 週次 1 コマンドで `data/public/public.sqlite3` と `dist/` が更新される
- `tmp/review/` の CSV が運用判断に使える

## Phase 3: Data quality loop
- unmatched/suspects の継続トリアージ
- alias/evidence の蓄積と再発防止

**DoD**
- 未解決率がトラッキングされ、改善施策が回っている

## Non-goals in WBS
- `buildings_master` 再構築フローの復帰
- canonical 自動上書きの導入
