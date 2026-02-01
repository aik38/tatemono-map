# Runbook（運用）

## 定期実行
- 週2回 ingest を実行（例：火・金 10:00）
- 実行：scripts\run_ingest.ps1

## 静的HTML生成
- Phase 2 で実装する静的HTML生成CLIを実行し、`dist/index.html` と `dist/b/{building_key}.html` を生成する
- 生成手順はCLI実装後にこのセクションへ追記する（入口は本ドキュメントに固定）

## 失敗時
- 例外は握りつぶさず、管理者へLINE通知
- Web/APIは停止しない（最終更新日時が古い状態で継続）
- 更新が失敗した場合は、前回生成済みの静的HTMLを維持し、復旧後に再生成する
