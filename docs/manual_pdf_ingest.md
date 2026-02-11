# Manual PDF(CSV) ingest runbook

本ドキュメントは、正式ルート「手動で保存した PDF → ChatGPT で CSV 化 → DB upsert → dist build」を固定化するための手順です。

## 1. 手順（概要）
1. 物件 PDF を手動で保存する。
2. ChatGPT で CSV に変換する。
3. `tmp/manual/ulucks_pdf_raw.csv` として保存する。
4. PowerShell から `scripts/run_ulucks_manual_pdf.ps1` を実行する。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\run_ulucks_manual_pdf.ps1" -NoServe
```

## 2. CSV スキーマ（正本）
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

## 3. 取り込み仕様
- 取り込みCLI: `python -m tatemono_map.cli.ulucks_manual_run --csv tmp/manual/ulucks_pdf_raw.csv --db data/tatemono_map.sqlite3 --output dist --no-serve`
- `rent_man` / `fee_man` は万円として解釈し、円整数へ変換（×10000）。
- `building_key` は `building_name|address|structure|age_years` を使い stable hash で生成。
- `listing_key` は建物キーと公開用集計に必要な値を使う stable hash で生成。
- `room_label` は公開事故防止のため常に `NULL` 固定。
- 取り込み後に `building_summaries` を `listings` から再集計して更新。

## 4. 公開禁止情報（注意）
- 号室 / 部屋番号
- 参照元 URL（smartlink 含む）
- 管理会社名 / 電話番号
- 連絡先メール情報

manual ルートでも、公開HTML（`dist`）には上記を出力しない運用を徹底します。
