# Runbook（手動一次資料 → CSV → 合算の正本）

## 0. このRunbookの目的
- 対象は **手動一次資料（PDF ZIP / 保存HTML）をCSV化し、建物マスターへ合算** する運用のみ。
- Webは図鑑として完結し、LINE導線の入口にする（WBS Phase2/4準拠）。
- Webへは公開NG情報（号室/参照元URL/会社情報/PDFリンク）を出さない。

## 1. repo固定（最重要）
PowerShellは必ず次の先頭2行を入れて実行する。

```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO
```

- 本リポの `.ps1` は `-RepoPath` を受け取り、内部でも `Set-Location $REPO` する。
- `.git` と `pyproject.toml` が無い場所では失敗し、repo外誤実行を防ぐ。

## 2. tmp/manual の固定I/O契約

```text
tmp/manual/
  inputs/
    html_saved/                         # mansion-review等の保存HTML（一次資料）
    buildings_master/
      buildings_master_primary.csv      # 合算の主系入力（固定名）
      buildings_master_secondary.csv    # 合算の従系入力（固定名）
  outputs/
    mansion_review/<timestamp>/
      mansion_review_<timestamp>.csv    # 保存HTML→CSV成果物
    buildings_master/
      buildings_master.csv              # 合算の最終成果物（固定名）
```

補足:
- PDF ZIPパイプラインの成果物は `tmp/pdf_pipeline/out/<timestamp>/final.csv`。
- `tmp/manual/inputs/buildings_master/*.csv` は、必要に応じて `final.csv` や `mansion_review_*.csv` から整形して配置する（運用上の固定受け口）。

## 3. 迷わない手順（コピペ運用）

### 3-1. 初回セットアップ
```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -RepoPath $REPO
```

### 3-2. PDF ZIP（Downloads最新）→ CSV
```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_pdf_zip_latest.ps1 -RepoPath $REPO
```

- 入力: `Downloads` の `リアプロ-*.zip` / `ウラックス-*.zip`（最新ファイルを採用）。
- 出力: `tmp/pdf_pipeline/out/<timestamp>/final.csv, stats.csv`。

### 3-3. 保存HTML → CSV
```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_mansion_review_html.ps1 -RepoPath $REPO
```

- 入力: `tmp/manual/inputs/html_saved/`。
- 出力: `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv`。

### 3-4. 建物マスター合算（固定名）
```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_merge_building_masters.ps1 -RepoPath $REPO
```

- 入力（固定名）:
  - `tmp/manual/inputs/buildings_master/buildings_master_primary.csv`
  - `tmp/manual/inputs/buildings_master/buildings_master_secondary.csv`
- 出力（固定名）:
  - `tmp/manual/outputs/buildings_master/buildings_master.csv`

## 4. QC（最低限）

```powershell
$csv = "tmp\pdf_pipeline\out\<timestamp>\final.csv"
$rows = Import-Csv $csv
"building_name empty = {0}/{1}" -f (($rows | ? { [string]::IsNullOrWhiteSpace($_.building_name) }).Count), $rows.Count
"address empty      = {0}/{1}" -f (($rows | ? { [string]::IsNullOrWhiteSpace($_.address) }).Count), $rows.Count
```

- `stats.csv` の `status / warning_count / reasons` を必ず確認。
- 欠損率が高い場合は一次資料・抽出ルールの再確認を優先。

## 5. Git同期（運用）
```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\push.ps1 -RepoPath $REPO -Message "your commit message"
```

## 6. 残置ファイルについて
- `tmp/manual/ulucks_pdf_raw.csv` は **旧運用互換のため残置**。
- 新規運用は本Runbookの固定I/O契約を使用する。
