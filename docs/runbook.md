# Runbook（運用）

## 定期実行
- 週2回 ingest を実行（例：火・金 10:00）
- 実行：scripts\run_ingest.ps1

## 失敗時
- 例外は握りつぶさず、管理者へLINE通知
- Webは停止しない（最終更新日時が古い状態で継続）
