# tatemono-map（手動一次資料 → CSV 固定化リポジトリ）

## 1) これは何か（30秒で理解）
- このリポジトリは **手動で集めた一次資料（ZIP/PDF/保存HTML）を、再現可能な手順でCSV化する** ための運用基盤です。
- 現時点の正本は次の2本です。
  - **A. PDF（Ulucks / Realpro）→ CSV**
  - **B. 保存HTML（mansion-review）→ CSV**
- venv は必ず **`\.venv\Scripts\python.exe` を直接指定**して使います（Activate前提にしない）。

---

## 2) 最短で動かす（Quickstart）

### 2-1. 初回セットアップ
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

### 2-2. PDF ZIP（Downloadsの最新）→ CSV
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_pdf_zip_latest.ps1
```

- 成果物は `tmp/pdf_pipeline/out/<timestamp>/` に作成されます。
  - `final.csv`
  - `stats.csv`
  - `manifest.csv`
  - `qc_report.txt`

### 2-3. mansion-review 保存HTML → CSV
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_mansion_review_html.ps1
```

- 成果物は `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv` に作成されます。

---

## 3) 手動パイプライン（正）

## A. PDF（Ulucks / Realpro）→ CSV

### 入力
- `Downloads` の ZIP（最新を自動採用）
  - `リアプロ-*.zip`
  - `ウラックス-*.zip`

### 実行（最新ZIP自動）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_pdf_zip_latest.ps1
```

### 実行（ZIPを明示指定）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_pdf_zip.ps1 `
  -RealproZip "C:\path\リアプロ-20260218.zip" `
  -UlucksZip "C:\path\ウラックス-20260218.zip" `
  -QcMode warn
```

### 固定インターフェイス（CLI）
`src/tatemono_map/cli/pdf_batch_run.py` は次を受け付けます（`--zip` はありません）。
- `--realpro-dir`
- `--ulucks-dir`
- `--out-dir`
- `--qc-mode` (`strict|warn|off`)
- `--legacy-columns`

### 出力
- 中間: `tmp/pdf_pipeline/work/<timestamp>/...`（展開/集約）
- 成果: `tmp/pdf_pipeline/out/<timestamp>/final.csv, stats.csv`

## B. 保存HTML（mansion-review）→ CSV

### 入力
- 保存HTMLを `tmp/manual/inputs/html_saved/` に置く（単一ファイル指定も可）

### 実行
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_mansion_review_html.ps1
```

### 出力
- `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv`

### 最小カラム
- `building_name`
- `address`
- `area`
- `city`
- `ward`
- `source_url`
- `source_file`

---

## 4) QC（必須）

### stats.csv の見方
- `status=OK|WARN|SKIP` で PDF単位の抽出品質を確認。
- `warning_count` と `reasons` で要確認PDFを特定。

### final.csv の欠損率（building_name / address）
```powershell
$csv = "tmp\pdf_pipeline\out\<timestamp>\final.csv"
$rows = Import-Csv $csv
"building_name empty = {0}/{1}" -f (($rows | ? { [string]::IsNullOrWhiteSpace($_.building_name) }).Count), $rows.Count
"address empty      = {0}/{1}" -f (($rows | ? { [string]::IsNullOrWhiteSpace($_.address) }).Count), $rows.Count
```

---

## 5) トラブルシュート

### 違うPythonで動かしてしまう
- **必ず** `\.venv\Scripts\python.exe` を使ってください。
- `python` / `py` の素実行は環境依存で事故の元です。

### `Advanced encoding /90msp-RKSJ-H` 警告
- 文字コード系の警告は、処理完走する場合があります。
- 重要なのは `final.csv` / `stats.csv` の欠損・崩れ有無です。
- 警告有無より **抽出品質（欠損率・QC reason）** を優先判断します。

---

## 6) 禁止事項
- 推測だけで抽出ロジックを変更しない。
- fixture（再現HTML/PDF断片）なしで修正しない。
- ZIP/PDF/生HTMLなど巨大一次資料をコミットしない。
- 一時ファイルをルート直下へ散乱させない（`tmp/manual/inputs` / `tmp/pdf_pipeline/work` に集約）。

---

## 固定フォルダ構造（運用正本）
```text
docs/
  spec.md
  runbook.md
scripts/
  setup.ps1
  run_pdf_zip_latest.ps1
  run_pdf_zip.ps1
  run_mansion_review_html.ps1
  mansion_review_html_to_csv.py

tmp/
  manual/
    inputs/
      pdf_zips/
      html_saved/
    outputs/
      mansion_review/
  pdf_pipeline/
    work/<timestamp>/
    out/<timestamp>/
```

---

## 旧構造からの移行メモ
- 旧運用 `tmp/manual/ulucks_pdf_raw.csv` は互換のため残しています。
- 新規一次資料は、次の固定先を使ってください。
  - PDF ZIP: `tmp/manual/inputs/pdf_zips/`
  - 保存HTML: `tmp/manual/inputs/html_saved/`

詳細は `docs/runbook.md` を参照してください。
