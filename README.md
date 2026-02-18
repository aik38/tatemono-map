# tatemono-map

## Why（目的）
- **建物図鑑として公開する静的HTML** を再現可能に生成するためのリポジトリです。
- 手動データ収集（PDF ZIP / 保存HTML）→ CSV化 → 建物マスター合算までを運用として固定します。
- **公開禁止情報（号室 / 参照元URL / 会社情報 / PDFリンク / 認証情報）を公開物に含めない**ことを前提にしています。

## 正本ドキュメント
- 仕様の正本: `docs/spec.md`
- 工程の正本: `docs/wbs.md`
- 運用手順の正本: `docs/runbook.md`

## Git運用（必須）
Git操作は必ず以下のスクリプトを使用してください。
- 同期: `scripts/git_sync.ps1`
- コミット/プッシュ: `scripts/git_push.ps1`

`git_push.ps1` は、機密・作業場・生成物の禁止ファイルが追跡されている場合に停止します。

```powershell
$REPO = "C:\path\to\tatemono-map"

# 最新化（fast-forward only）
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\git_sync.ps1 -RepoPath $REPO

# 変更確認後にコミット/プッシュ
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\git_push.ps1 -RepoPath $REPO -Message "docs: update runbook"
```

## ローカル生成物の取り扱い
- `secrets/**` と `.tmp/**` はローカル専用です。
- `tmp/manual/inputs/**` `tmp/manual/outputs/**` `tmp/pdf_pipeline/**` はローカル運用ディレクトリです（`.gitkeep` のみ追跡）。
- リポジトリ直下の `*.csv` はコミットしません。

## パイプライン（概要）
```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_pdf_zip_latest.ps1 -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_mansion_review_html.ps1 -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_merge_building_masters.ps1 -RepoPath $REPO
```

詳細は `docs/runbook.md` を参照してください。
