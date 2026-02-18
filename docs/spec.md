# spec（手動一次資料→CSV→合算フェーズ）

## スコープ（作るもの）
1. Ulucks / Realpro PDFバッチを安定してCSV化する。
2. mansion-review 保存HTMLを最小カラムでCSV化する。
3. `tmp/manual` 固定I/O契約で建物マスターを合算する。
4. PowerShell 一発実行で再現できる運用を維持する。

## 非スコープ（今は作らない）
- 自動巡回の高度化
- API/DB機能の拡張
- 申込完結UI（LINE誘導のみ）

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

### 建物マスター合算（固定名）
- 入力:
  - `tmp/manual/inputs/buildings_master/buildings_master_primary.csv`
  - `tmp/manual/inputs/buildings_master/buildings_master_secondary.csv`
- 出力:
  - `tmp/manual/outputs/buildings_master/buildings_master.csv`

## 公開禁止・運用制約
- Web出力禁止: 号室 / 参照元URL / 会社情報 / PDFリンク。
- ZIP/PDF/保存HTMLなど巨大一次資料は Git にコミットしない。
- 推測修正を禁止し、fixtureベースでのみ修正する。
- 入出力の置き場は `tmp/manual/inputs`, `tmp/manual/outputs`, `tmp/pdf_pipeline/work`, `tmp/pdf_pipeline/out` に固定する。
