# Runbook（運用）

## Smartlink 一発運用（推奨）
## Smartlink URL取り扱い注意（重要）
- smartlink URL は **opaque文字列** として扱い、parse/正規化/再構築をしない（`mail=%40` と `mail=@` の混在を壊さないため）。
- 次ページは URL を組み立てず、ページ内ページネーションの `a[href]` を抽出して、その href をそのまま辿る。

- リポジトリ実体は **`$env:USERPROFILE\tatemono-map` 固定**（OneDrive 配下は使用しない）。
- 実行手順とコマンドは README の Quick Start を正本とする（A: build-only / B: ingest）。
- Smartlink URL は PowerShell で壊れないよう **単一引用符** を使い、`mail=` は `%40` 形式で指定する。

## UI確認（build-only）
- 実行手順とコマンドは README の Quick Start A を参照（この runbook では重複掲載しない）。
- `SQLITE_DB_PATH` を未指定で運用する場合は `data\tatemono_map.sqlite3` が使われる。

## PowerShell スクリプトの静的確認（ローカル）
- `scripts/run_ulucks_smartlink.ps1` の ParserError を事前検知する場合は、ローカル Windows / PowerShell で次を実行する。
  - `pwsh -NoProfile -Command "[void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path '.\\scripts\\run_ulucks_smartlink.ps1'), [ref]$null, [ref]$errors); if ($errors) { $errors | Format-List; exit 1 }"`

## OneDrive 配下を避ける理由（事故例）
- 統一運用: **`$env:USERPROFILE\tatemono-map` を唯一の実体パス**にする。
- OneDrive 配下では同期/ロックの影響で、次の連鎖障害が起きやすいです。
  - `Set-Location` 失敗
  - `fatal: not a git repository`
  - venv 未有効化による `ModuleNotFoundError`
  - build 未到達で `dist/index.html` 不在
- 推奨運用: `$env:USERPROFILE\tatemono-map` に実体を置き、Desktop はショートカットのみ。

## 定期実行（Phase3）
- 週2回 ingest を実行（例：火・金 10:00）
- 実行：scripts\run_ingest.ps1
  - ingest 成功後に build を行い、dist に反映する
  - build は dist__tmp に生成してから dist に反映するため、build 失敗時は dist は更新されない（前回分維持）
- 動作確認（成功/失敗）：`pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ingest.ps1` / `pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ingest.ps1 -FailIngest`
- ULUCKS smartlink PoC（PowerShell例）
  - `pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ingest.ps1 -UluSmartlinkUrl 'https://ulucks.example/smartlink/?link_id=YOUR_LINK_ID&mail=user%40example.com'`
  - `SQLITE_DB_PATH` を指定しない場合は `data\tatemono_map.sqlite3` が使われる
  - `tmp_ulucks_*.html` は smartlink のデバッグ生成物なのでコミット不要（`dist_tmp/` など Git 管理外に出力）


## smartlink_dom デバッグ手順（証拠ベース）
- 実行例（HTML/スクショ保存付き）
  - `pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ingest.ps1 -Mode smartlink_dom -StartUrl 'https://ulucks.example/smartlink/?link_id=YOUR_LINK_ID&mail=user%40example.com' -DebugDir tmp/smartlink_dom_debug -Headed`
- 失敗時は `tmp/smartlink_dom_debug/<timestamp>/<page_index>_*/` に `meta.json` / `page.png` / `page.html` が残る。
- PowerShell で HTML 内の確認例
  - `Select-String -Path tmp\smartlink_dom_debug\*\*\page.html -Pattern '検索結果|空室一覧|所在地|家賃|間取り|専有面積|更新'`

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
- `python -m pytest`
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
