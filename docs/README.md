# docs index（ドキュメント入口）

このディレクトリは、運用判断に必要な文書の入口です。  
迷ったら以下の順で読んでください。

## 推奨読書順
1. [wbs.md](wbs.md)  
   WBS（Work Breakdown Structure / 作業分解構成）。工程、DoD（Definition of Done / 完了条件）、禁止事項の正本。
2. [spec.md](spec.md)  
   運用仕様の正本。canonical 方針、責務、禁止事項、更新ポリシー。
3. [runbook.md](runbook.md)  
   実運用手順。初回 seed、週次 1 コマンド運用、レビュー CSV 対応手順。
4. [../PLAN.md](../PLAN.md)  
   プロジェクト方針（目的、優先順位、変更管理ルール）。
5. [data_contract.md](data_contract.md)  
   入出力データ契約（CSV/DB/配信物）。

## 補助ドキュメント
- [ops_weekly_checklist_a4.md](ops_weekly_checklist_a4.md): 毎週運用のA4チェックカード（最小PDCA）。
- [ops_unmatched_report.md](ops_unmatched_report.md): unmatched簡易集計スクリプトの使い方。
- [ops_ci_testing.md](ops_ci_testing.md): PagesとPR CI（pytest）の役割分担。
- [frontend_versions.md](frontend_versions.md): フロント関連の履歴メモ。
- [manual_pdf_ingest.md](manual_pdf_ingest.md): PDF取り込みの補助手順。
- [ulucks_phase_a.md](ulucks_phase_a.md): Ulucks 作業メモ。
- [roadmap_pr3_auto_add_buildings.md](roadmap_pr3_auto_add_buildings.md): unmatched を今は捨てる方針と、PR3自動追加の再開計画。

## Legacy（deprecated）
- [legacy/README.md](legacy/README.md): 現行 canonical 運用では使わない旧フロー資料。
- ⚠️ 参照専用です。運用は `scripts/weekly_update.ps1` / `scripts/publish_public.ps1` / building_registry を使用してください。
