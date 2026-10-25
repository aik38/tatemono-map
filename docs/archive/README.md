# 建物マップ — 過去文書・復元索引

**現行の主要仕様は [README](../../README.md) と [docs索引](../README.md) を参照してください。** このフォルダは記録の保全先であり、旧操作手順を現行の本番正本へ実行する目的ではありません。

## 2026年10月25日 — 主要6文書への整理前の完全保存

- **固定SHA:** `cb5dbe2d20132bce3391908298145701f554192a`
- **保存ブランチ:** [archive/docs-before-consolidation-20261025](https://github.com/aik38/tatemono-map/tree/archive/docs-before-consolidation-20261025)
- **固定コミット全体:** [整理前のリポジトリ](https://github.com/aik38/tatemono-map/tree/cb5dbe2d20132bce3391908298145701f554192a)
- この時点で存在した**README・PLAN・cloud/README・docs全体（整理前の主要13ファイルを含む）をGit履歴として一式保存**しています。
- **ブランチを移動せず固定SHAを復元根拠とすること。** 本番SQLite/GCS HEADのバックアップではなく、GitHub文書とコードの時点スナップショットです。

| 旧全文の参照 | 固定版 |
| --- | --- |
| README | [README.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/README.md) |
| PLAN | [PLAN.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/PLAN.md) |
| Cloud運用・実績 | [cloud/README.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/cloud/README.md) |
| spec | [docs/spec.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/docs/spec.md) |
| データフロー | [docs/data_flow_and_sources_of_truth.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/docs/data_flow_and_sources_of_truth.md) |
| Runbook | [docs/runbook.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/docs/runbook.md) |
| 旧データ契約 | [docs/data_contract.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/docs/data_contract.md) |
| 旧WBS | [docs/wbs.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/docs/wbs.md) |
| 旧週次確認カード | [docs/ops_weekly_checklist_a4.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/docs/ops_weekly_checklist_a4.md) |
| 旧CI説明 | [docs/ops_ci_testing.md](https://github.com/aik38/tatemono-map/blob/cb5dbe2d20132bce3391908298145701f554192a/docs/ops_ci_testing.md) |
| Docs一式 | [docsディレクトリ](https://github.com/aik38/tatemono-map/tree/cb5dbe2d20132bce3391908298145701f554192a/docs) |

表示・復元例（まず読み取り専用）:

```bash
git show cb5dbe2d20132bce3391908298145701f554192a:README.md
git show cb5dbe2d20132bce3391908298145701f554192a:docs/data_contract.md
git show cb5dbe2d20132bce3391908298145701f554192a:docs/wbs.md
```

## 2026年10月19日 — 以前のCloud整理前の完全保存

- ブランチ: [backup/docs-pre-cloud-alignment-20261019](https://github.com/aik38/tatemono-map/tree/backup/docs-pre-cloud-alignment-20261019)
- 固定SHA: `03be5e82c5dcc65f1d4960f0da421024cefa3e27`
- [README全文](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/README.md) / [旧Docs全体](https://github.com/aik38/tatemono-map/tree/03be5e82c5dcc65f1d4960f0da421024cefa3e27/docs)

旧Windows手動運用・会社8/小倉北区PoC・過去Work引継ぎは当時の事実として保持します。旧版の「未実装」「未公開」「公開ID制限」を現在の仕様へ戻しません。古いローカルSQLiteを現在のGCS正式正本へ上書きしません。
