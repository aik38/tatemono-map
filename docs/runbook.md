# Runbook（手動CSVパイプライン正本）

## 0. 対象
- 本runbookは、**手動で収集した一次資料をCSV化する運用**のみを対象にします。
- 自動巡回・バックエンド拡張は対象外です。

## 1. 事前準備
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

- 以降は `.venv\Scripts\python.exe` を常に使用します。

## 2. PDF（Ulucks / Realpro）

### 2-1. 最新ZIP自動採用
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_pdf_zip_latest.ps1
```

### 2-2. ZIP指定
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_pdf_zip.ps1 `
  -RealproZip "C:\path\リアプロ-YYYYMMDD.zip" `
  -UlucksZip "C:\path\ウラックス-YYYYMMDD.zip" `
  -QcMode warn
```

### 2-3. 出力確認
- 成果物: `tmp/pdf_pipeline/out/<timestamp>/final.csv, stats.csv`
- 作業領域: `tmp/pdf_pipeline/work/<timestamp>/...`

## 3. 保存HTML（mansion-review）

### 3-1. 入力配置
- `tmp/manual/inputs/html_saved/` に保存HTMLを置く（複数可）。

### 3-2. 実行
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_mansion_review_html.ps1
```

### 3-3. 出力確認
- `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv`

## 4. QC
- `stats.csv` の `status`, `warning_count`, `reasons` を確認する。
- `final.csv` の欠損率を必ず見る。

```powershell
$csv = "tmp\pdf_pipeline\out\<timestamp>\final.csv"
$rows = Import-Csv $csv
"building_name empty = {0}/{1}" -f (($rows | ? { [string]::IsNullOrWhiteSpace($_.building_name) }).Count), $rows.Count
"address empty      = {0}/{1}" -f (($rows | ? { [string]::IsNullOrWhiteSpace($_.address) }).Count), $rows.Count
```

## 5. 運用ルール
- 一次資料（ZIP/PDF/生HTML）は Git 管理しない。
- 推測で抽出ロジックを変更しない（fixture追加とセット）。
- ルート直下への `tmp_*.html` など散乱を禁止し、`tmp/manual/inputs` へ集約する。
