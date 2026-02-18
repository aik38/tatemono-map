# tatemono-map

## Why（目的）
- tatemono-map は、**手動一次資料（PDF ZIP / 保存HTML）を CSV 化し、building master まで再現可能に合算する**ための運用リポジトリです。
- 目的は「毎回同じ入口・同じ I/O 契約・同じ安全ガード」で、作業者が変わっても同じ成果物に到達することです。

## Non-goals（やらないこと）
- 一次資料の自動収集そのものをこの運用の正本にはしない（手動入手が前提）。
- 既存 Python 実処理のロジック改造はしない（本件は I/O 契約・PS ラッパ・ドキュメント固定が対象）。
- Web 公開物へ内部運用情報を露出しない。

## 公開禁止情報（絶対に push / 公開しない）
- 号室情報（`room_no`, `unit`, `号室` など）
- 参照元 URL（`source_url` など）
- 管理会社・担当者などの内部連絡情報
- 生 PDF / ZIP / 認証情報 / `secrets/**` / `.tmp/**`

## 正本ドキュメント
- 仕様の正本: [`docs/spec.md`](docs/spec.md)
- 工程の正本: [`docs/wbs.md`](docs/wbs.md)
- 運用の正本: [`docs/runbook.md`](docs/runbook.md)

## データフロー（1枚）
- **A: PDF ZIP 系**
  - `tmp/manual/inputs/pdf_zips/`（Ulucks / RealPro ZIP）
  - → `scripts/run_pdf_zip_latest.ps1`
  - → `tmp/pdf_pipeline/out/<timestamp>/final.csv`
  - → `tmp/manual/inputs/buildings_master/buildings_master_primary.csv`（運用で整形配置）
- **B: 保存 HTML 系（mansion-review）**
  - `tmp/manual/inputs/html_saved/`
  - → `scripts/run_mansion_review_html.ps1`
  - → `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv`
  - → `tmp/manual/inputs/buildings_master/buildings_master_secondary.csv`（運用で整形配置）
- **Merge（primary wins）**
  - `scripts/run_merge_building_masters.ps1`
  - → `tmp/manual/outputs/buildings_master/buildings_master.csv`

## Quickstart（コピペ）
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\setup.ps1") -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\run_pdf_zip_latest.ps1") -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\run_mansion_review_html.ps1") -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\run_merge_building_masters.ps1") -RepoPath $REPO
```

## GitHub ↔ ローカル同期（実行場所非依存）
`C:\Users\OWNER` など repo 外からでも、次の形式だけ使ってください（`./scripts/...` は禁止）。

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "sync.ps1")
```

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "push.ps1") -Message "docs: update runbook" -SensitiveColumnPolicy strict
```

- `sync.ps1` / `push.ps1` は内部で `scripts/git_sync.ps1` / `scripts/git_push.ps1` を呼び出します。
- `push.ps1` は、`secrets/**` `.tmp/**` `tmp/**（.gitkeep 以外）` ルート `*.csv` の tracked 混入を検知すると停止します。
- `SensitiveColumnPolicy` を `strict` にすると、CSV ヘッダに禁止情報系カラムがあれば push を停止します（`warn` は警告のみ）。

## tmp/manual / tmp/pdf_pipeline の固定契約
- `tmp/manual/inputs/{pdf_zips,html_saved,buildings_master}/`
- `tmp/manual/outputs/{mansion_review,buildings_master}/`
- `tmp/pdf_pipeline/{work,out}/`

詳細な I/O 契約と復旧手順は [`docs/runbook.md`](docs/runbook.md) を参照してください。
