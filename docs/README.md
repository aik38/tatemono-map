# docs index

README から最初に読むべきドキュメントを整理した索引です。

## Recommended reading order
1. [spec.md](spec.md)
   - システムの目的、正本（canonical）概念、非ゴールを定義。
2. [runbook.md](runbook.md)
   - 初回 seed と週次 1 コマンド運用の手順。
3. [data_contract.md](data_contract.md)
   - 入力 CSV と公開成果物の契約。
4. [wbs.md](wbs.md)
   - 運用・改善タスクのフェーズ管理。

## Other docs
- [frontend_versions.md](frontend_versions.md)
  - フロントエンド関連の変更メモ。
- [manual_pdf_ingest.md](manual_pdf_ingest.md)
  - PDF 処理の補足手順。
- [ulucks_phase_a.md](ulucks_phase_a.md)
  - Ulucks 向け作業メモ。

> 注意: このリポジトリの現行運用は `buildings` canonical DB を中心にした seed + weekly update です。
> 旧来の `buildings_master` 再構築フローは現行 runbook では採用しません。
