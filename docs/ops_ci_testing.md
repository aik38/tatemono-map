# CI・Cloud配置・収集・公開の責務

2026-10-19 JST時点のWorkflowを照合した説明です。

| Workflow / 起動元 | 実際の責務 | 成功から分かる範囲 |
| --- | --- | --- |
| [ci.yml](../.github/workflows/ci.yml) `pull_request` | 必須テスト・全体比較、Docker build、コンテナ内Chromium合成確認 | コード回帰検証。実Ulucks収集や本番配置は行わない |
| [cloud_deploy.yml](../.github/workflows/cloud_deploy.yml) / `Deploy Ulucks cloud collector` | mainの対象path pushでtest。deployはdispatchや特定コミットmarker等の条件を満たす時のみ | testと配置を区別。通常main pushが常に収集を起動するわけではない |
| Cloud Scheduler → Cloud Run | 通常週次のfresh会社判定・PDF取得・解析・正本/リリース更新 | execution・HEAD・会社別証跡を確認して実収集を判断 |
| [deploy_pages.yml](../.github/workflows/deploy_pages.yml) / `Deploy GitHub Pages` | 公開リリース確認、公開DB取得・検証、render、Pages配置、実Web照合 | release_check/build/deployと各ステップ結果を区別 |

## Pagesの発火・省略・設定確認

- main push（path制限なし）、毎時23分（`23 * * * *`）、Cloud配置Workflowのmain成功後`workflow_run`、手動dispatchが入口です。
- `cloud/check_release.py`はschedule時にGCS HEADと実Web markerのrun ID/公開SHAを比較し、変更なしならbuild/deployを省略します。通常pushは変更なしでもbuild対象です。
- Cloud有効時はWIFでHEADと公開専用SQLiteを読み、generation・SHA・件数を照合します。Git管理の旧公開DBを本番正本にしません。
- buildではID集合・集約値・禁止情報等を検証し、deploy後に`verify_public --production`で実Webを照合します。
- deploy末尾の`cloud/enable_scheduler.py`は予定/宛先を検証し、ENABLEDなら変更なし、PAUSEDならresumeします。従って文書だけのpushでも本番側ステップを動かし得ます。

## 文書だけの変更

Workflowの変更や本番の再収集・再配置を伴わずに文書を反映する場合、発火条件を必ず確認します。今回の文書整合PRは通常のPR CIを実行し、main反映コミットに`[skip ci]`を指定してpush起点の本番処理を抑止する方針です。Workflow設定そのものは変更しません。

GitHubのskip命令はpush/pull_requestに適用され、scheduleやworkflow_run自体を停止する設定ではありません。通常の毎時チェック・週次収集は維持します。必要なチェックやリポジトリ規則を無効化・迂回せず、安全に反映できない場合はPRで停止します。

参照: [GitHub公式skip仕様](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs)。

## 実績の読み方

テスト成功≠Cloud配置成功≠実収集成功≠正本更新成功≠Pages配置成功≠実Web一致です。変更なしの定時skipも、新規収集や公開の証明にはしません。既存失敗と新規失敗を比較するCIの判定はそのまま尊重し、今回の文書更新のために全件データを再生成しません。
