# Runbook（運用）

## Smartlink 一発運用（推奨）
- どの作業ディレクトリからでも、以下の 1 コマンドで ingest → normalize → build → ブラウザ表示まで実行します。
  - `pwsh -File scripts/run_ulucks_smartlink.ps1 -Url "<smartlink_url>"`
- 主なオプション
  - `-RepoPath`: リポジトリのフルパスを明示（未指定時は `C:\dev\tatemono-map` → `$env:USERPROFILE\tatemono-map` → `$env:USERPROFILE\OneDrive\Desktop\tatemono-map` を探索）
  - `-MaxItems`: 取り込み上限（既定 200）
  - `-Port`: `http.server` ポート（既定 8080）
  - `-NoServe`: サーバ起動せず `dist/index.html` を直接開く
- 失敗時メッセージ（原因と次アクション）
  - `RepoPath が見つからない`: clone先の確認、または `-RepoPath` を明示
  - `-Url が空`: ブラウザで開ける smartlink URL を `-Url` に指定
  - ingest 0件: smartlink 期限切れ/無効の可能性。ログイン状態で smartlink 再生成後に再実行

## OneDrive 配下を避ける理由（事故例）
- OneDrive 配下では同期/ロックの影響で、次の連鎖障害が起きやすいです。
  - `Set-Location` 失敗
  - `fatal: not a git repository`
  - venv 未有効化による `ModuleNotFoundError`
  - build 未到達で `dist/index.html` 不在
- 推奨運用: `C:\dev\tatemono-map` または `$env:USERPROFILE\tatemono-map` に実体を置き、Desktop はショートカットのみ。

## 定期実行（Phase3）
- 週2回 ingest を実行（例：火・金 10:00）
- 実行：scripts\run_ingest.ps1
  - ingest 成功後に build を行い、dist に反映する
  - build は dist__tmp に生成してから dist に反映するため、build 失敗時は dist は更新されない（前回分維持）
- 動作確認（成功/失敗）：`pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ingest.ps1` / `pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ingest.ps1 -FailIngest`
- ULUCKS smartlink PoC（PowerShell例）
  - `pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ingest.ps1 -UluSmartlinkUrl "<smartlink_url>"`
  - `SQLITE_DB_PATH` を指定しない場合は `data\tatemono_map.sqlite3` が使われる
  - `tmp_ulucks_*.html` は smartlink のデバッグ生成物なのでコミット不要（`dist_tmp/` など Git 管理外に出力）

## 静的HTML生成
- 静的HTML生成CLIを実行し、`dist/index.html` と `dist/b/{building_key}.html` を生成する
- 実行例（PowerShell）
  - `$env:SQLITE_DB_PATH="data\\tatemono_map.sqlite3"`
  - `python -m tatemono_map.render.build --output-dir dist`
- 公開 output（Phase2）は建物単位のみ。号室（例: `205:`）・部屋一覧・参照元URL・管理会社情報・PDF情報は公開しない
- オペレーター向け private output を作る場合のみ、次を使う（公開 dist からは未参照）
  - `python -m tatemono_map.render.build --output-dir dist --private-output-dir dist_private`
- 禁止情報（号室/参照元URL/元付・管理会社/見積内訳PDFなど）が混入した場合は生成が失敗する

## Phase2 主要変更（運用メモ）
- 静的HTML生成CLI：`python -m tatemono_map.render.build --output-dir dist`
- building_summaries が空でも最低1件（seed）を出して `dist/b/*.html` を0件にしない
- `dist/` はビルド成果物で Git 管理しない（.gitignore で除外）
- 禁止情報（URL/PDF/号室/参照元/管理会社等）が dist に混入しないチェックを継続し、各ページに「最終更新日時」を必須表示
- `python -m ...` が repo 直下から動く（PYTHONPATH 追加不要の方向へ寄せた）
- 既知の警告：Pydantic/FastAPI の deprecation warning は「動作影響なし、後でまとめて対応」でOK

## ローカル検証（pytest → build → dist確認）
- `pytest`
- `python -m tatemono_map.render.build --output-dir dist`
- `ls dist dist\\b`

## 失敗時（Phase3）
- ingest が失敗した場合：
  - 例外は握りつぶさない（run_ingest.ps1 は非0で終了）
  - DBはトランザクションでロールバックされるため「半端に更新された状態」を残さない
  - Web/API は継続（dist は前回生成分が残るため）
  - 対応：ログを確認 → 原因修正 → run_ingest.ps1 を再実行 → 成功後に dist が更新される
- build が失敗した場合：
  - dist には反映しない（前回分維持）
  - 禁止情報混入チェックにより落ちる想定。データを修正して再実行する
  - まずは DB の必須カラムが NULL になっていないか疑う（name/address/vacancy_status/last_updated など）
  - stub ingest を再実行して上書きする（例：`python -m tatemono_map.ingest.stub --db data\\tatemono_map.sqlite3`）
