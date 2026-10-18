# Work B 公開同期：本番作業引継ぎ
更新時点: 2026-10-19 JST。以下は途中状態。未完了を完成と扱わない。

## 保存済みコード
- 変更前main: 290b588f690f5c251c473aa23586c4455bb0feea
- 実装main: ea9567ef0c1cad813f363d918c743b47c5fe8f82
- PR #379: https://github.com/aik38/tatemono-map/pull/379
- PR CI成功（必須・全体比較・Docker/Chromium）: https://github.com/aik38/tatemono-map/actions/runs/39138012334
- 全体の既存失敗20件、新規失敗0件。実装後のmain配置workflowのtestも成功。
- この引継ぎ更新は文書だけ。実行イメージのコードSHAは上記実装main。

## 正式GCS HEAD：公開専用更新は完了
project tatemono-map / region asia-northeast1 / bucket tatemono-map-poc-523194690131
- state/current.json generation: 1792335903106932
- release: 20261018T150227Z-f7fc07ea9a53
- master: masters/20261018T150227Z-f7fc07ea9a53.sqlite3
  - generation 1792335894756651
  - SHA256 85f8b639c0ddb6cc64dc06bacdb5f1eed7ec315e06f0980a442adeaa3d8df456
- public: public/releases/20261018T150227Z-f7fc07ea9a53/public.sqlite3
  - generation 1792335901169385
  - SHA256 bd252d1b60f331b503bf4c792465f20fa4ee1028d24c566ab1f576d7afa0db51
- 正本7,556棟、hidden_from_public=1は6棟、公開DB7,550棟、公開空室7,000件。
- 公開予定JSON7,550件。既存6,875件のID・名称・住所・URLは事前照合で維持。
- 488棟: 487棟を公開対象、全明細が保留へ撤回された仮登録1棟のみ既存hidden設定で明示的に隔離。ID・原文・履歴は維持。
- 91棟: 正式採用の86棟を公開対象、既存hidden指定5棟を維持。一括恒久除外なし。
- 名称・住所だけの検索除外102件を廃止。異なる正式名称・住所に矛盾する古いaliasはページ統合に使わず、履歴自体は未変更。
- 今回新規取得PDFは0。収集証跡は 20261018T131235Z-5ac1145986ff から世代・SHA・current snapshotを検証して継承。
- listings58,862、sale_listings11,907、raw_sources122,031と全履歴・alias・他社snapshotを維持。
- 通常の新規採用もhidden条件だけで公開。全明細保留になった新規仮登録をprivate raw履歴へ移す最小修正を含む。

## 実行中／未完了
1. 修正済みCloud Run imageの配置（収集なし）:
   https://github.com/aik38/tatemono-map/actions/runs/39138548455
   test成功、deployのimage buildが進行中。merge marker WORK_B_PUBLICATION_DEPLOY_ONLY と ULUCKS_DEPLOY_ONLY=true により収集を起動しない。
2. 新正式HEADを使うPages:
   https://github.com/aik38/tatemono-map/actions/runs/39138925727
   dispatch済み。再dispatchを重ねず既存runを観測する。
3. 本番cloud_release.json、JSON ID集合、実ページ、配置後JobとSchedulerの最終照合。
4. 月曜04:00 JSTの無人定期実行は未来で未実証。確認だけの全社再収集は禁止。

## バックアップと切戻し制約
- コード: backup/work-b-start-20261018（変更前main）
- GCS: deployment-backups/work-b-20261018T143800Z/
  - manifest.json: 変更前HEAD・世代/SHA付きmaster/public・Job/Scheduler設定・旧実Web JSON/marker
  - job.before.yaml: gcloud export形式の復旧可能な旧Job設定、SHA256 f9babf8a0c5cf2607705857ef44361a29f9953af40c597abd21bb9e83cad88b1
  - old-pages.zip: 変更前の完全Pages artifact。元markerとの一致を確認。
    SHA256 1140b91a82e890a2e696e682d253386331e2c174e668ba2f2bda28c91a2cc535
  - migration-audit.private.json: ID別分類・原文証跡。public GitHubへコピー禁止。
- 変更前release: 20261018T131235Z-5ac1145986ff / HEAD generation 1792329282447313。
- 旧master SHA256 8775b879304c1f772084c0aea5dd7be605bc93fa76b87066fb8a794ed9041753。
- 旧public SHA256 c8c089be5dea1569fd93427b10b5f39757874984025dd23d38e6bcaeb85abf61。
- HEAD切戻しは現在のHEADが上記変更後release・generationと一致し、後発収集も稼働中実行もない場合だけCASで行う。後発成功成果を巻き戻さない。
- Job復旧も変更後の想定generation/imageが現在と一致する場合だけ。新しい設定を推測で上書きしない。

## 再開する具体的操作
既存Cloud Shell: ~/work/work-b/code（実装コード）、~/work/work-b/（private成果・ログ）。
追加認証や初期接続の再実行は不要。
1. 最新main、state/current.json世代、Cloud Run実行中の有無を再確認。旧値で上書きしない。
2. gh run view 39138548455 --repo aik38/tatemono-map と gh run view 39138925727 --repo aik38/tatemono-map で既存runを確認。
3. GCS公開専用releaseは既に成功。~/work/work-b/release.py を再実行しない。Ulucks収集をdispatchしない。
4. Pages成功後、PYTHONPATH=src python -m tatemono_map.cloud.fetch_public --bucket tatemono-map-poc-523194690131 --output ~/work/work-b/verification/public.sqlite3 --marker ~/work/work-b/verification/cloud_release.json を実行。
5. PYTHONPATH=src python -m tatemono_map.cloud.verify_public --marker ~/work/work-b/verification/cloud_release.json --production で実Webと全ID指紋・公開集約値を照合。
6. 配置後Jobが実装SHAのimageと TATEMONO_SOURCE_COMMIT を使い、args=-m tatemono_map.cloud.run、all_companies/kitakyushu、復旧用環境変数なしを確認。SchedulerはENABLED、0 4 * * 1、Asia/Tokyoを維持。
7. Pages artifact内の全建物ページ・JSON・sitemap ID集合と、追加/既存の実URLを確認してこの文書を実績へ更新する。
8. 通常週次との接続は公開専用HEAD→fresh batch→新規採用→自動公開の統合テストで成功。次の実際の定刻実行の成功と混同しない。

## 後続結果追記（2026-10-19 JST文書整合時）

上の「途中状態」「実行中／未完了」「再開する具体的操作」は保存時点の原記録です。原文を変更せず、後続の確認結果を追記します。完了済み操作を再実行する指示ではありません。

- [Cloud配置 #39138548455](https://github.com/aik38/tatemono-map/actions/runs/39138548455)はsuccess。収集なしのWork B配置を完了。
- 手動Pages #39138925727はcancelled。後続の[Pages #39139167694](https://github.com/aik38/tatemono-map/actions/runs/39139167694)がrelease_check/build/deployを完了し、実Web照合・Scheduler確認もsuccess。
- 当該runログにrelease `20261018T150227Z-f7fc07ea9a53`、公開DB/検索JSON7,550、公開空室7,000を確認。上記正本7,556・hidden6の内訳を当該リリースの履歴値として維持し、現在値に固定しない。
- [後続schedule #39142974069](https://github.com/aik38/tatemono-map/actions/runs/39142974069)はrelease_check success、build/deploy skipped。変更なし確認であり新収集ではない。
- 現行の正式採用非hidden建物は自動公開し、旧公開DBを許可リストにしない。追加の毎週人間承認なし。
- 2026-10-19 04:00 JSTの定刻無人収集は文書整理時点では未来。Scheduler設定/確認成功と定刻収集成功は区別し、後者は未実証。
- 今回は文書のみ。Ulucks再収集、republish、Cloud Run実行/配置、GCS HEAD/DB更新、Scheduler/Workflow設定変更は実施しない。

現在の手順は[Cloud README](README.md)と[Runbook](../docs/runbook.md)を参照します。
