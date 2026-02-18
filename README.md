# tatemono-map

## Overview（Why / 目的）
- このリポジトリは **手動一次資料（PDF ZIP / 保存HTML）をCSV化し、建物マスターへ合算する正本フロー** を固定するための運用リポジトリです。
- Webは **図鑑として完結** させ、申込導線はLINEへ集約します（WBS Phase2/4方針）。

## 制約（公開NG）
- Web出力禁止: **号室 / 参照元URL / 会社情報 / PDFリンク**。
- 一次資料（ZIP/PDF/保存HTML）はGitにコミットしない。
- 推測修正は禁止（fixtureを追加して再現性を担保）。

## 正本ドキュメント
- 仕様: `docs/spec.md`
- 工程/WBS: `docs/wbs.md`
- 運用手順（迷わない手順）: `docs/runbook.md`

## Quickstart（最短導線）
> すべて **repo root で実行**。各PowerShellは内部で repo root へ `Set-Location` し、repo外実行をガードします。

```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_pdf_zip_latest.ps1 -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_mansion_review_html.ps1 -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_merge_building_masters.ps1 -RepoPath $REPO
```

- PDF ZIP成果物: `tmp/pdf_pipeline/out/<timestamp>/final.csv`
- 保存HTML成果物: `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv`
- 合算成果物（固定）: `tmp/manual/outputs/buildings_master/buildings_master.csv`

## GitHub ↔ ローカル同期
```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO
# pull
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -RepoPath $REPO
# 編集・確認後に push
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\push.ps1 -RepoPath $REPO -Message "your commit message"
```

詳細運用・固定ファイル名は `docs/runbook.md` を参照してください。
