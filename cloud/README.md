# Ulucksクラウド本番運用

2026-10-19 JST更新。会社8・小倉北区限定の初期PoCは過去の段階です。現在はUlucks対象会社を自動判定し、北九州全域（22子エリア）を収集する構成です。

## 現在の構成

| 項目 | 本番設定・役割 |
| --- | --- |
| Project / Region | `tatemono-map` / `asia-northeast1` |
| Cloud Run Job | `tatemono-collection-poc`（名前は継続、通常argsは`-m tatemono_map.cloud.run`） |
| Scheduler | `tatemono-ulucks-weekly`、月曜04:00 JST、`0 4 * * 1` / `Asia/Tokyo` |
| GCS bucket | `tatemono-map-poc-523194690131` |
| 正式正本 | `state/current.json`の`master`が指す世代固定SQLite |
| 公開DB | 同じHEADの`public`が指す公開専用SQLite |
| Pages | `.github/workflows/deploy_pages.yml`、毎時23分のリリース確認等 |

通常週次の構成は **Scheduler → Cloud Run → fresh会社判定・PDF取得 → private原本保存 → 解析・名寄せ・QC → 正本更新 → GCSリリース/HEAD更新 → Pages同期・実Web照合**。Windows PC・Work・ローカルファイルは不要です。Secret Manager・WIF・既存サービスアカウントを使い、認証情報を文書やGitHubへコピーしません。

## 通常週次と実証の範囲

`collection_mode=all_companies`、`area_id=kitakyushu`。対象会社は実際の利用可能経路で判定し、申請が必要な会社などは利用不可の証跡を残します。対象一覧の変化や取得失敗は正常0件ではありません。

通常週次はfresh census・新規PDF取得です。復旧用の成功成果再利用・replayは通常設定と区別し、以前のpartial releaseやコードrevisionを通常収集開始の必須gateにしません。旧明細所有範囲が不明な部分は`preserve_unknown`として維持します。根拠のないbaseline所有権を設定して旧募集を消しません。

初回実収集・正本更新・公開は成功済みです。SchedulerのENABLED記録、テスト成功、定刻無人実行成功は別の証拠です。文書整理時点では2026-10-19（月）04:00 JSTの定刻実行前で、当該実証は未確認です。確認目的だけの全社再収集をしません。

## PDF原本とprivate履歴

全社収集の主な保存先:

```text
private-runs/<run>/
  companies/<company-id>/
    pdf/000.pdf
    pdf/001.pdf
    parsed-rows.json
    review-rows.csv
  company-<company-id>-manifest.json
  company-<company-id>-evidence.json
  company-<company-id>-result.json
```

PDF原本を証拠として保存し、解析結果は建物名・住所・募集条件等へ構造化します。名寄せ・QCで正式採用/保留/異常/重複を分類し、正式採用だけを正本の有効募集へ反映します。manifest/evidenceと参照情報から会社・run・元PDF・generation・SHA-256・取得結果を追えます。

原本保存とSQLiteへの数値・文字列保存は両立します。`replay.py`は保存済みPDFの対象・時刻・件数・参照先等を検証して読み戻す復旧機能です。旧単社runには`private-runs/<run>/pdf/`形式もあります。保存期間・ライフサイクル・現存PDF総数は今回未確認で、永久保存は保証しません。

実装: [batch](../src/tatemono_map/cloud/batch.py)、[pipeline](../src/tatemono_map/cloud/pipeline.py)、[replay](../src/tatemono_map/cloud/replay.py)、[storage](../src/tatemono_map/cloud/storage.py)。

## 正式正本・GCS・安全性

- 更新前に`backups/<run>.sqlite3`へ正本をバックアップします。
- HEADが指すmaster/publicをgeneration固定で取得し、SHA-256・DB integrity・件数・canonical/履歴保持を検証します。
- `masters/<run>.sqlite3`と`public/releases/<run>/public.sqlite3`を保存した後、期待generationによるCASで`state/current.json`を切り替えます。
- `state/collection-lock.json`のcollection leaseで同時更新を抑止します。失敗時に別実行のleaseを削除しません。
- 全社バッチは安全に採用できる会社のpartial_successを保存し得ます。失敗会社のsnapshotは保持し、致命的QC失敗やCAS不一致で正式commitできないrunはHEADを切り替えません。
- 賃貸優先順位Ulucks ＞ RealPro ＞ Mansion Review賃貸、分譲系統・他社snapshot・過去履歴を維持します。

正本と公開用DBの役割は[データフロー](../docs/data_flow_and_sources_of_truth.md)を参照。PDF・raw・review・認証情報はprivateに置き、Pagesは正本やPDFを取得せず公開専用データだけを使います。

## Pages公開同期

`deploy_pages.yml`はmain push、毎時23分、Cloud配置Workflow成功後、手動dispatchの入口を持ちます。`cloud/check_release.py`は定時チェックで本番markerとHEADのrun/SHAを比較し、同じ場合はbuild/deployを省略します。通常pushは変更なしでもビルド対象です。

`fetch_public`がHEADの公開専用SQLiteをgeneration・SHA・件数付きで検証し、既存renderがHTML/検索JSON/サイトマップを生成します。`verify_public`で公開ID集合・集約値を検証し、デプロイ後に実Webの`cloud_release.json`・公開JSON等を照合します。

Work Bでは正式採用の非hidden建物を原則自動同期します。旧公開DBは欠落防止用で、新規公開の許可リストではありません。名称・住所一致だけで別IDを消さず、整合する明示的canonical aliasだけをページ統合に使います。毎週の追加公開承認はありません。

### 公開専用処理

`python -m tatemono_map.cloud.republish`は再ログイン・再収集せず、既存正式採用情報から公開リリースを再構成する処理です。元収集証跡の世代・SHA・current snapshotを検証して継承し、collection leaseとHEAD CASを使います。通常は正本内容を保持します。既存CLIの例外隔離指定は正本のhidden変更を伴うため、通常の公開処理とは区別します。

これは読み取り専用コマンドではなくGCSリリース/HEADを書き換えます。必須引数は`--bucket`、`--work`、`--expected-generation`、`--source-commit`。通常週次の追加審査や調査時の再実行手順にはしません。

## 公開実績と証拠

以下は**リリース`20261018T150227Z-f7fc07ea9a53`の時点値**で、将来の現在値・固定期待値ではありません。

| 項目 | 当該リリースの記録 |
| --- | ---: |
| 正式正本の建物 | 7,556棟 |
| 公開DB / 検索JSON | 7,550棟 / 7,550件 |
| 公開空室 | 7,000件 |
| 明示的非公開 | 6棟 |
| Ulucks追加488棟 | 487棟公開、全明細保留の仮登録1棟を既存hiddenで隔離 |
| 過去未公開91棟 | 86棟公開、既存hiddenの5棟は維持 |
| 今回のPDF再取得 | 0件 |

- [Cloud配置 #39138548455](https://github.com/aik38/tatemono-map/actions/runs/39138548455): success。収集なしの配置。
- [Pages #39139167694](https://github.com/aik38/tatemono-map/actions/runs/39139167694): release_check/build/deploy成功。本番Web照合とScheduler有効状態確認ステップもsuccess。
- 当該runログでrelease ID、公開DB7,550・空室7,000・検索JSON7,550を確認。正本・6棟差の内訳/世代/SHAは[Work B引継ぎ](HANDOFF_WORK_B_PUBLICATION.md)に記録。
- [後続定時チェック #39142974069](https://github.com/aik38/tatemono-map/actions/runs/39142974069): release_check成功、build/deploy skipped。新規収集・新リリースの実証を意味しません。

## 障害・復旧

まず既存実行・正式HEAD・private証跡・公開markerを読み取り専用で確認します。[Runbook](../docs/runbook.md)を使用し、再収集・初期接続・IAM準備・再配置・公開専用更新を診断目的で繰り返しません。

切戻し前には最新HEAD generation、master/public参照、Jobの稼働中有無を再確認します。後発正常リリースがある場合は古い成果へ戻しません。バックアップ復旧は期待generationと対象を固定した別の変更作業です。

## 初回移行・過去資料

[初期Cloud文書全文（固定コミット）](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/cloud/README.md)にはIAM/WIF準備、Windows正本候補照合、初期bootstrap・旧PoC手順を保存しています。現在の週次手順として実行しません。

[Work A引継ぎ](HANDOFF_ULUCKS_FULLAREA.md)・[Work B引継ぎ](HANDOFF_WORK_B_PUBLICATION.md)は原記録を維持し、後続結果を追記しています。[履歴索引](../docs/archive/README.md)から旧README/Docsも復元できます。RealPro・Mansion Reviewの同等クラウド収集完成はこのUlucks実績から推定しません。
