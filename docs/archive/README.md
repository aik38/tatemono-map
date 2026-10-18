# 旧文書の履歴・復元索引

## 保存目的

Windows中心の手動運用、会社8・小倉北区限定PoC、初回クラウド移行、Work A/Bの判断経緯を失わず、現行仕様と区別して参照できるようにします。旧資料は現在の本番手順として実行しません。

## 保全済みの全体バックアップ

- ブランチ: [`backup/docs-pre-cloud-alignment-20261019`](https://github.com/aik38/tatemono-map/tree/backup/docs-pre-cloud-alignment-20261019)
- 固定SHA: `03be5e82c5dcc65f1d4960f0da421024cefa3e27`
- [固定コミット全体](https://github.com/aik38/tatemono-map/tree/03be5e82c5dcc65f1d4960f0da421024cefa3e27)

2026-10-19 JSTの作業開始時にブランチの参照先と固定SHAの一致を読み取り確認しました。ブランチの変更・削除・上書きは行いません。mainへ全文を大量複製せず、Git履歴を正確な復元元にします。

| 旧全文 | 固定版リンク |
| --- | --- |
| README | [README.md](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/README.md) |
| 方針 | [PLAN.md](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/PLAN.md) |
| Docs一式 | [docs/](https://github.com/aik38/tatemono-map/tree/03be5e82c5dcc65f1d4960f0da421024cefa3e27/docs) |
| 旧Runbook | [runbook.md](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/docs/runbook.md) |
| 初回移行・PoC | [cloud/README.md](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/cloud/README.md) |

特定ファイルの読み出し例（復元表示のみ。本番へ書き戻さない）:

```bash
git show 03be5e82c5dcc65f1d4960f0da421024cefa3e27:README.md
git show 03be5e82c5dcc65f1d4960f0da421024cefa3e27:docs/runbook.md
```

## 移行の要点と現在の参照先

現在はScheduler → Cloud Run → private PDF保存 → 解析・精査 → GCS SQLite正式正本 → 公開専用DB → Pagesです。旧ローカルDB/CSV/ZIPを本番基準にはせず、Windowsは開発・手動補助です。

Work Bで正式採用の非hidden建物を原則自動公開し、旧公開ID制限を廃止しました。曖昧・異常な未採用行は引き続きprivate保留です。「公開待ち」と「未採用」を混同しません。

- [現行README](../../README.md) / [文書索引](../README.md) / [現行Cloud文書](../../cloud/README.md)
- [Work A原記録と追記](../../cloud/HANDOFF_ULUCKS_FULLAREA.md)
- [Work B原記録と追記](../../cloud/HANDOFF_WORK_B_PUBLICATION.md)

引継ぎ中の「未完了」や当時の「公開しない」制約は当時の記録で、後続実績・現行仕様は追記と現行文書で確認します。日付付きの検証記録はその時点の証拠であり、現在状態の断定には使用しません。
