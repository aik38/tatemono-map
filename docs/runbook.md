# 本番Runbook（GCP中心）

2026-10-19 JST更新。[Cloud構成・実績](../cloud/README.md)、[仕様](spec.md)、[データフロー](data_flow_and_sources_of_truth.md)を前提とします。以下の確認は監視・障害対応用で、毎週人間が実行しないと収集や公開が進まない仕組みではありません。

## 通常週次の観測

1. Scheduler `tatemono-ulucks-weekly`の予定（月曜04:00 JST）と実際の起動結果を確認する。
2. 既存Job `tatemono-collection-poc`の該当executionを確認し、終了・失敗・稼働中を区別する。稼働中に二重起動しない。
3. GCS `state/current.json`のgeneration、run ID、source commit、QC、master/publicのobject・generation・SHA-256を記録する。
4. 会社別の成功・失敗・利用不可、採用・保留・異常・重複件数を確認する。partial_successを全会社完全成功と読み替えない。
5. 毎時23分のPages確認後、GCSの公開releaseと本番marker・JSONが一致することを確認する。

Scheduler設定のENABLED、テスト成功、実際の定刻無人実行成功は別の証拠です。今回の文書整理では2026-10-19 04:00 JSTの実行前であり、定刻収集を成功済みとは記載しません。

## 読み取り専用の確認例

認証済みCloud Shell等の作業checkoutで使用します。認証情報の表示・再登録や初期接続のやり直しは不要です。

```bash
gcloud scheduler jobs describe tatemono-ulucks-weekly --project tatemono-map --location asia-northeast1 --format='json(state,schedule,timeZone,httpTarget.uri,lastAttemptTime,status)'
gcloud run jobs executions list --job tatemono-collection-poc --project tatemono-map --region asia-northeast1 --limit=5
GCP_BUCKET=tatemono-map-poc-523194690131 python cloud/read_state.py
```

詳細executionは上で得た実名を使い、`gcloud run jobs executions describe <execution-name> --project tatemono-map --region asia-northeast1`で確認します。Secret値を取得しません。`read_state.py`はGCS HEADを読むだけで収集・更新しません。診断結果の保存・共有はprivate原則です。

## HEAD・generation・SHA・公開の照合

Cloudの読み取り権限を持つ環境で、公開専用DBとmarkerを検証用ディレクトリに取得できます。これはローカル検証ファイルの作成だけで、GCS HEAD/正本を変更しません。

```bash
python -m tatemono_map.cloud.fetch_public --bucket tatemono-map-poc-523194690131 --output work/verification/public.sqlite3 --marker work/verification/cloud_release.json
python -m tatemono_map.cloud.verify_public --marker work/verification/cloud_release.json --production
```

`fetch_public`はHEAD、収集証跡、generation固定ダウンロード、SHA-256、公開DB件数・整合性を検査します。`verify_public --production`は期待markerと実Webを照合します。処理中に新しいreleaseが公開された場合は「壊れた」と決めつけず、最新HEADと稼働中Pagesを読み直します。

確認先:

- [本番release marker](https://www.tatemono-map.com/cloud_release.json)
- [本番build情報](https://www.tatemono-map.com/build_info.json)
- [本番検索JSON](https://www.tatemono-map.com/data/buildings.v2.min.json)
- [Pages実行一覧](https://github.com/aik38/tatemono-map/actions/workflows/deploy_pages.yml)

実行の緑表示だけで判断せず、build/deployが実行されたか、変更なしでskipされたか、実Web照合ステップの結果を区別します。文書だけのmainコミットと、公開成果物の`git_sha`が異なること自体はデータ不整合ではありません。run ID・公開SHA・ID集合・集約値を基準にします。

## PDF原本・解析・保留の追跡

HEAD reportの`company_results`から該当会社の`result_ref`/`manifest_ref`を辿ります。公開専用releaseでは元の収集runの参照が継承されるため、現在release名の下にすべてのPDFがあるとは限りません。

主な保存先は`private-runs/<collection-run>/companies/<company-id>/pdf/*.pdf`、`parsed-rows.json`、`review-rows.csv`、同run直下の`company-<id>-manifest.json`/`company-<id>-evidence.json`です。manifestにはPDFとevidenceのobject・generation・SHA-256等があります。

必要なobjectだけを参照世代で読み、SHAを確認してprivate作業領域へ取得します。`GCSStore.download(ref, output)`がその既存実装です。バケット全体の再取得やreplay実行は単なる観測に不要です。PDF・raw・review・ログイン情報をGitHub/Pagesへコピーしません。原本数・保存期間・ライフサイクルは今回未確認です。

## 失敗時の扱い

| 症状 | 先に確認する内容 | 維持する状態 |
| --- | --- | --- |
| 会社の認証・取得失敗 | 該当会社のprivate evidence・失敗コード、既存execution | 失敗を0件化せず旧currentを保持 |
| 行の保留・異常 | parsed/reviewと正式採用の件数内訳 | 未採用値を公開せず他の正常採用を維持 |
| バッチQC/CAS失敗 | failure記録・現在HEAD generation・競合実行 | 正式commit前のHEADを保持 |
| Pagesが更新されない | HEAD/marker差、release_check/build/deploy各結果 | 正本やJobを触らず原因を特定 |
| 公開後照合失敗 | 期待marker・実Web・後発Pages実行 | 旧データへの即時巻戻しを避ける |

全社バッチは安全条件を満たす成功会社だけのpartial_successを正式保存する場合があります。「一社失敗なら全体のHEADは必ず不変」とは扱いません。正式commitできない失敗runはHEADを切り替えません。

## 復旧の条件

1. 最新HEADとgeneration、master/public世代・SHA、稼働中execution、最新Pagesを再確認する。
2. 復旧対象とバックアップの一致、後発の正常releaseがないことを確認する。古い引継ぎの値を現在値として使わない。
3. 正本/公開DBのバックアップとSQLite integrity・件数・ID・alias・履歴保持を検証する。
4. 書き込みが必要な復旧は対象・期待generationを固定し、collection leaseとCASを守る。新しい正常成果や別実行のleaseを上書き・削除しない。
5. 復旧後は公開marker・JSON・ID集合・集約値まで確認する。

`python -m tatemono_map.cloud.republish`は再収集なしの公開専用更新ですが、GCSリリース/HEADを書き換えるため、調査用コマンドではありません。[Cloud文書](../cloud/README.md#公開専用処理)を確認し、別の変更作業として扱います。replay、Cloud再配置、Scheduler resume、初期bootstrapも通常の確認手順に含めません。

## Windows・手動補助

PowerShell、手動PDF/CSV、correction等の既存機能は残っています。[ローカル開発](local_development.md)、[手動PDF](manual_pdf_ingest.md)、[correction仕様](building_corrections_csv.md)と[旧Runbook全文](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/docs/runbook.md)を参照してください。

これらのローカルDB・CSVはGCS正式正本に優先しません。ローカル公開DBをpushしただけでCloud有効時の本番データ更新が成立するとは扱いません。募集0件でも建物ID/URLを維持し、訂正は最新正本の安全な変更作業として切り分けます。
