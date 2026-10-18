# ドキュメント索引

2026-10-19 JST更新。現在はUlucksのGCP収集・GCS正式正本・Pages自動同期が本番経路です。

## 現行仕様を読む順序

| 順 | 文書 | 役割 |
| --- | --- | --- |
| 1 | [README](../README.md) / [PLAN](../PLAN.md) | 入口・目的・運用方針 |
| 2 | [spec](spec.md) | canonical保護、採用/保留、自動公開、snapshotの契約 |
| 3 | [データフローと正本](data_flow_and_sources_of_truth.md) | PDF原本、構造化データ、GCS正本、公開派生物 |
| 4 | [Cloud構成](../cloud/README.md) / [Runbook](runbook.md) | 通常週次・公開同期・監視・障害・復旧 |
| 5 | [データ契約](data_contract.md) | PDF/CSV/DB/ID/公開境界 |
| 6 | [CIと公開](ops_ci_testing.md) / [週次確認カード](ops_weekly_checklist_a4.md) | 検証責務・任意の監視項目 |
| 7 | [WBS](wbs.md) | 現在の完了・稼働・未実証・将来項目 |

## 開発・手動補助

- [ローカル開発と技術参照](local_development.md): プレビュー・UI設定等。クラウド本番の必須作業ではありません。
- [手動PDF/CSV](manual_pdf_ingest.md): 旧ルート/手動補助。通常週次はCloudで自動取得・解析。
- [correction CSV](building_corrections_csv.md): 例外修正の記録とdry-run。最新GCS正本への安全な適用は別作業。
- [unmatched集計](ops_unmatched_report.md): ローカル分析補助。

## 過去資料・引継ぎ

- [履歴・復元索引](archive/README.md): 旧README・Docs・Cloud全文の固定コミット参照。
- [Work A](../cloud/HANDOFF_ULUCKS_FULLAREA.md) / [Work B](../cloud/HANDOFF_WORK_B_PUBLICATION.md): 当時の記録と後続結果。
- [Ulucks Phase A](ulucks_phase_a.md): smartlink一覧解析の過去検証。現在の全社PDF経路とは別。
- [PR3旧計画](roadmap_pr3_auto_add_buildings.md): 高信頼auto-seed実装前の計画。
- [frontend履歴](frontend_versions.md)、日付付きの調査・改善計画は当該時点の参考資料です。

旧Windows運用や初期PoCの「未実証」「公開ID制限」等を現在の仕様へ戻しません。参照の優先順位は現行実装・本番実績を照合した上記仕様/Runbookです。
