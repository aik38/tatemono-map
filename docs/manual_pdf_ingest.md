# Manual PDF(CSV) ingest runbook

本ドキュメントは、正式ルート「手動で保存した PDF → ChatGPT で CSV 化 → DB upsert → dist build」を固定化するための正本です。

## 1. 正式ルート（PDF→CSV→DB→dist）

1. 新しい物件 PDF を手動で保存する（`tmp/manual/*.pdf`）。
   - 「60件」は管理画面プルダウンの**表示件数の例**です。PDF件数そのものは管理会社・検索条件で変動し、10〜500件以上になることがあります。
   - 物件別PDFはCSV化しやすく有利ですが、1 PDF が長すぎるとCSV化事故が増えるため、目安として **200〜300件程度で分割**（エリア/条件ごとに複数PDF）を推奨します。
2. PDF の内容を ChatGPT などで CSV 化する。
3. CSV を保存する（ファイル名は任意）。運用上は投入用の固定パス `tmp/manual/ulucks_pdf_raw.csv` を推奨します。
   - 履歴を残す場合の例: `ulucks_pdf_raw_YYYYMMDD.csv` として保存し、投入前に `ulucks_pdf_raw.csv` へコピーする。
4. リポジトリ直下で次を実行する。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ulucks_manual_pdf.ps1 -CsvPath tmp/manual/ulucks_pdf_raw.csv -NoServe -Open
```

- スクリプトはどこから起動しても `scripts` の場所から repo ルートを解決します。
- `-NoServe` 指定時のみ `--no-serve` を CLI に付けます（`store_true` フラグ事故防止）。

運用コマンド例（1ブロック）:

```powershell
# 任意CSVを指定（-CsvPath）して投入し、HTTPサーバは起動せず（-NoServe）、生成した index.html を開く（-Open）
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ulucks_manual_pdf.ps1 -CsvPath tmp/manual/ulucks_pdf_raw_20260211.csv -NoServe -Open
```

## 2. 直接CLIでの Quickstart（サーバ起動なし）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Set-Location $REPO
. .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m tatemono_map.cli.ulucks_manual_run --csv <任意のCSVパス> --db data/tatemono_map.sqlite3 --output dist --no-serve
Start-Process dist/index.html
```

## 3. CSV スキーマ（正本）

列名は次を正本とします（不足列は空欄で可）。

- `building_name`
- `address`
- `layout`
- `rent_man`（万円）
- `fee_man`（万円）
- `area_sqm`
- `updated_at`
- `structure`
- `age_years`

## 4. 取り込みと建物図鑑の挙動

- 取り込みCLI: `python -m tatemono_map.cli.ulucks_manual_run --csv ... --db ... --output dist --no-serve`
- `rent_man` / `fee_man` は万円として解釈し、円整数へ変換（×10000）。
- `room_label` は公開事故防止のため常に `NULL` 固定。
- 取り込み後に `building_summaries` は `listings` から再集計されます。
- 建物図鑑の想定挙動は「**建物（building）は残り続け、空室（listings）が更新される**」です。

## 5. ファイル配置と Git 運用

- `tmp/manual/` は手動運用の作業領域です。
- `tmp/manual/*.pdf` と `tmp/manual/*.csv` は **Git管理しません**（個人情報/禁止情報の混入リスク）。
- 公開HTML（`dist`）には、号室/参照元URL/管理会社/PDF等の禁止情報を出力しません。

## 6. よくあるエラーと対処

- **`ModuleNotFoundError: tatemono_map`**
  - `.venv` 未有効化、`PYTHONPATH=src` 未設定、または repo 直下以外での実行が原因です。
  - 対処: `Set-Location <repo>`, `.\.venv\Scripts\Activate.ps1`, `$env:PYTHONPATH="src"` を確認。

- **scripts のパス間違い**
  - カレントディレクトリ依存で `scripts/run_ulucks_manual_pdf.ps1` が見つからないことがあります。
  - 対処: repo 直下で `-File .\scripts\run_ulucks_manual_pdf.ps1` を実行するか、フルパス指定で実行。

- **`forbidden data detected` / `pattern=号室`**
  - 原因: `building_name` や `address` に号室/部屋番号が混入したまま `dist` 生成に進んでいる。
  - 対策: CSV化時点で建物名から `◯◯号室` / `◯◯号` を除去し、`room` 列へ寄せてから再実行する。
