# クラウド週次運用の確認カード

2026-10-19 JST更新。監視・障害確認の補助であり、人間の毎週の作業や公開承認を自動運用の必須条件にはしません。[Runbook](runbook.md)参照。

| 確認点 | 判断する内容 |
| --- | --- |
| Scheduler | 月曜04:00 JSTの実際の起動結果。ENABLED設定だけで成功扱いしない |
| Cloud Run | 該当executionの完了/失敗/稼働中。二重起動しない |
| 収集品質 | 会社別成功/失敗/利用不可、採用/保留/異常/重複の内訳。失敗≠正常0件 |
| 正式HEAD | run ID、generation、QC、master/public参照とSHA。後発releaseを優先 |
| 原本・履歴 | 必要時だけmanifest/evidenceからprivate PDF・解析・reviewを辿る |
| 公開同期 | 毎時23分の確認結果。変更なしならbuild/deploy skippedで正常 |
| 実Web | marker、公開JSON、ID集合・集約値と正式releaseが一致 |
| 建物保護 | 募集0件建物・ID・URL・他ソースsnapshot・履歴を維持 |
| 例外 | 保留は別途精査。正式採用の非hidden建物の自動公開を承認待ちにしない |

文書整理時点では次回2026-10-19 04:00 JSTの定刻実行は未来です。未実証の結果を先にチェック済みにしません。

Windows起動、ZIP配置、ローカルDB更新、手動publish、確認目的の全社再収集は通常週次の必須作業ではありません。異常時はまず既存証跡を読み取り、最新HEADと稼働中Jobを確認します。設定変更や復旧更新は監視と分けます。
