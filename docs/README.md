# 建物マップ — ドキュメント索引

更新: **2026年10月25日 JST**。

普段の運用では**次の主要6文書だけ**を参照します。同じ説明を別ファイルにコピーせず、担当文書へリンクしてください。

| 入口 | 文書 | ここに書く内容 |
| --- | --- | --- |
| 1 | [README](../README.md) | 建物マップの目的・現在の到達状況・公開実績 |
| 2 | [PLAN](../PLAN.md) | 今後の優先順位・開発方針・未完了 |
| 3 | [仕様・データ契約](spec.md) | 建物ID・名寄せ・採否・賃貸/分譲・公開禁止情報 |
| 4 | [3情報源と正本のデータフロー](data_flow_and_sources_of_truth.md) | Job、Scheduler、原本、SQLite、GCS、Pages |
| 5 | [本番運用と障害復旧](runbook.md) | 週次チェック・診断・バックアップ・ロールバック |
| 6 | **この索引** | 最新主要文書と専門資料・歴史資料の区別 |

## 専門資料

以下は必要な場合だけ参照し、通常運用の仕様を上書きしません。

- [ローカル開発・UI技術参照](local_development.md)
- [手動PDF/CSV技術資料](manual_pdf_ingest.md)
- [建物例外訂正CSV](building_corrections_csv.md)
- [フロントバージョン履歴](frontend_versions.md)
- [unmatched分析補助](ops_unmatched_report.md)
- [RealPro自動取得の実装証拠（2026-10-24）](../cloud/REALPRO_AUTOMATION_20261024.md)
- [Mansion Review週次実装](../src/tatemono_map/cloud/mansion_weekly.py) / [限定再判定](../src/tatemono_map/cloud/mansion_limited.py)
- [Cloud補助入口](../cloud/README.md)（独立した運用仕様の複製ではない）

## 統合後の旧ドキュメント

以下のURLには短い移転案内だけを残し、全文は[2026-10-25以前の履歴](archive/README.md)で保存します。

- [旧データ契約](data_contract.md) → [spec](spec.md)
- [旧週次確認カード](ops_weekly_checklist_a4.md) → [runbook](runbook.md)
- [旧CI・公開説明](ops_ci_testing.md) → [runbook](runbook.md)
- [旧WBS](wbs.md) → [PLAN](../PLAN.md)

## 履歴資料・過去の実験

- [整理前README・Docs一式の固定履歴と復元方法](archive/README.md)
- [Ulucks初期引継ぎ](../cloud/HANDOFF_ULUCKS_FULLAREA.md) / [公開同期の引継ぎ](../cloud/HANDOFF_WORK_B_PUBLICATION.md)
- [旧PR3計画](roadmap_pr3_auto_add_buildings.md)、[旧Ulucks Phase A](ulucks_phase_a.md)
- [Mansion Review 2026-03調査](mansion_review_batch2_investigation_20260327.md)、[2026-03改善計画](minimal_backend_improvement_plan_20260327.md)、[門司区canary](moji_canary_baseline_20260405.md)、[2026-10-16監査](../cloud/AUDIT_20261016.md)

**履歴文書の「未実装」「未完成」「当時は非公開」は当時の記録です。現在の仕様は主要6文書と実装・正式GCS HEAD・実Webの証拠を優先します。**
