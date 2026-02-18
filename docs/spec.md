# spec（手動CSV化フェーズ）

## スコープ（作るもの）
1. Ulucks / Realpro PDFバッチを安定してCSV化する。
2. mansion-review 保存HTMLを最小カラムでCSV化する。
3. 実行手順を PowerShell 一発で再現可能にする。

## 非スコープ（今は作らない）
- 自動巡回の高度化
- API/DB機能の拡張
- UI改善

## データ契約

### PDF pipeline 出力
- `tmp/pdf_pipeline/out/<timestamp>/final.csv`
- `tmp/pdf_pipeline/out/<timestamp>/stats.csv`

### mansion-review HTML 出力
- `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv`

最小カラム:
- `building_name`
- `address`
- `area`
- `city`
- `ward`
- `source_url`
- `source_file`

## 公開禁止・運用制約
- ZIP/PDF/保存HTMLなど巨大一次資料は Git にコミットしない。
- 推測修正を禁止し、fixtureベースでのみ修正する。
- 入出力の置き場は `tmp/manual/inputs`, `tmp/manual/outputs`, `tmp/pdf_pipeline/work`, `tmp/pdf_pipeline/out` に固定する。
