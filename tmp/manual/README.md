# tmp/manual（手動一次資料フローの固定 I/O 契約）

## 入力（inputs）
- `inputs/pdf_zips/`
  - 手動入手した PDF ZIP（Ulucks / RealPro）を保管する。
- `inputs/html_saved/`
  - mansion-review 等の保存 HTML（一次資料）を置く。
- `inputs/buildings_master/buildings_master_primary.csv`
  - 合算の主系入力（固定ファイル名）。
- `inputs/buildings_master/buildings_master_secondary.csv`
  - 合算の従系入力（固定ファイル名）。

## 出力（outputs）
- `outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv`
  - 保存 HTML → CSV の成果物。
- `outputs/buildings_master/buildings_master.csv`
  - 建物マスター合算の最終成果物（固定ファイル名）。

## 関連ディレクトリ（PDF パイプライン）
- `tmp/pdf_pipeline/work/`
  - PDF 処理の作業領域。
- `tmp/pdf_pipeline/out/<timestamp>/final.csv`
  - PDF ZIP → CSV の成果物。

## 追跡ポリシー
- `tmp/manual/README.md` と `.gitkeep` は追跡可。`tmp/manual` / `tmp/pdf_pipeline` の生成物は原則 `.gitignore` 対象。
- 詳細な実行手順は `docs/runbook.md` を正本とする。
