# Runbook（運用）

## 定期実行
- 週2回 ingest を実行（例：火・金 10:00）
- 実行：scripts\run_ingest.ps1

## 静的HTML生成
- 静的HTML生成CLIを実行し、`dist/index.html` と `dist/b/{building_key}.html` を生成する
- 実行例（PowerShell）
  - `$env:SQLITE_DB_PATH="data\\tatemono_map.sqlite3"`
  - `python -m tatemono_map.render.build --output-dir dist`
- 禁止情報（号室/参照元URL/元付・管理会社/見積内訳PDFなど）が混入した場合は生成が失敗する

## 失敗時
- 例外は握りつぶさず、管理者へLINE通知
- Web/APIは停止しない（最終更新日時が古い状態で継続）
- 更新が失敗した場合は、前回生成済みの静的HTMLを維持し、復旧後に再生成する
