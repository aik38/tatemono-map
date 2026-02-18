# tmp/manual（手動一次資料フローの固定I/O契約）

## 入力（inputs）
- `inputs/html_saved/`
  - mansion-review 等の保存HTML（一次資料）を置く。
- `inputs/buildings_master/buildings_master_primary.csv`
  - 合算の主系入力（固定ファイル名）。
- `inputs/buildings_master/buildings_master_secondary.csv`
  - 合算の従系入力（固定ファイル名）。

## 出力（outputs）
- `outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv`
  - 保存HTML→CSV の成果物。
- `outputs/buildings_master/buildings_master.csv`
  - 建物マスター合算の最終成果物（固定ファイル名）。

## 互換運用
- `tmp/manual/ulucks_pdf_raw.csv` は旧運用互換のため残置。
- 新規運用は `docs/runbook.md` の手順を正本とする。
