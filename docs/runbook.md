# 本番運用・監視・障害復旧Runbook

更新: **2026年10月27日 JST**。3情報源の週次実行と実Web照合を一本化した**唯一の主要運用手順書**です。実装仕様は[spec](spec.md)、保存先は[データフロー](data_flow_and_sources_of_truth.md)を参照。

> 本書は監視・障害対応用。**毎週人間が起動・承認しなければ更新できない設計ではありません。** Windows・Work・ローカルPDF/ZIP・手動CSVは通常の必須工程に含めません。

## 週次起動（JST）

| 順 | Scheduler | Cloud Run Job | 定時 |
| --- | --- | --- | --- |
| 1 | `tatemono-ulucks-weekly` | `tatemono-collection-poc` | 木曜14:00 |
| 2 | `tatemono-realpro-weekly` | `tatemono-realpro-weekly` | 木曜14:05 |
| 3 | `tatemono-mansion-weekly` | `tatemono-mansion-weekly` | 木曜14:10 |

週次基準は直近の木曜14:00（Asia/Tokyo）。木曜14:00より前は前週木曜が基準。次回起動は2026年10月29日（木）14:00／14:05／14:10。RealProは当該木曜14:00以降のUlucks実行の終了を待ち、Mansion Reviewは同じ木曜基準でUlucks・RealPro両方の終了を待つ。RealProの既定Cycleは `weekly-YYYY-MM-DD`、Mansion Reviewは `week-YYYYMMDD`（基準木曜の日付）。明示 `--cycle` と過去の保存済みCycleは維持する。**Job終了≠処理成功**。SchedulerのENABLED、テスト成功、Cloud Run配置成功、代表2社成功を全対象の週次成功と扱わない。

## 週次確認カード

1. **Scheduler:** 当該木曜の起動履歴と設定、Job起動が実際にあったか。
2. **Cloud Run:** 3Jobのexecution・開始/終了時刻・成功/失敗/再試行/稼働中。失敗・待機中を成功とみなさない。
3. **対象と原本:** Ulucksの判定対象全社・北九州全域、RealProの取得可能全社、Mansion Reviewの35市区町村。PDF/HTMLの保存証跡、対象外/失敗/未処理の数を区別。
4. **解析・採否:** 解析・正式採用・保留・異常・重複、source別currentと上位募集の保護を確認。partial_success≠全対象成功。
5. **正式HEAD:** `state/current.json`の最新run ID・generation・master/public object世代とSHA・QCを照合。
6. **Pages・実Web:** Pagesのrelease_check/build/deploy/verifyを確認し、公開marker・検索JSONの建物/賃貸集計と一致するか検証。**分譲件数は別途**公開SQLiteの`building_summaries.sale_listing_count`集計とWeb表示を比較する。標準のrelease markerや`verify_public`が分譲件数まで検証するとは扱わない。
7. **異常と復旧:** 新しい正常なリリースを保護し、実行中Jobの二重起動と無用な再取得を避ける。

2026-10-26の初回全対象・同一週・定刻の独立実証は、その日の**実際のexecutionと公開値**で判定する。予定があることだけで検証済みと記さない。

## 読み取り専用のコマンド例

GCP認証済みのCloud Shell等で利用。Secretの中身を出力しない。

```bash
gcloud scheduler jobs list --project tatemono-map --location asia-northeast1
gcloud run jobs executions list --job tatemono-collection-poc --project tatemono-map --region asia-northeast1 --limit 5
gcloud run jobs executions list --job tatemono-realpro-weekly --project tatemono-map --region asia-northeast1 --limit 5
gcloud run jobs executions list --job tatemono-mansion-weekly --project tatemono-map --region asia-northeast1 --limit 5
GCP_BUCKET=tatemono-map-poc-523194690131 python cloud/read_state.py
```

必要なら該当実行名で`gcloud run jobs executions describe <execution-name> --project tatemono-map --region asia-northeast1`。未完了の実行があれば再起動しない。原本はmanifest/evidenceが指す**対象objectだけ**を世代・SHA固定で調査し、PDF/HTML・private review・ログイン情報をGitHub/Pagesへ公開しない。

## 正本・実Webの照合

```bash
python -m tatemono_map.cloud.fetch_public --bucket tatemono-map-poc-523194690131 --output work/verification/public.sqlite3 --marker work/verification/cloud_release.json
python -m tatemono_map.cloud.verify_public --marker work/verification/cloud_release.json --production
```

上記は**検証用ファイルを生成する読み取り専用の照合**。GCS正本やWebを更新しない。

- [本番のリリース](https://www.tatemono-map.com/cloud_release.json) / [build_info](https://www.tatemono-map.com/build_info.json) / [公開検索JSON](https://www.tatemono-map.com/data/buildings.v2.min.json)
- [Pages実行履歴](https://github.com/aik38/tatemono-map/actions/workflows/deploy_pages.yml)
- [Cloud配置Workflow](../.github/workflows/cloud_deploy.yml) はmainの関連パス変更でテストが走るが、通常pushが常に収集・配置を起動するわけではない。
- [PR CI](../.github/workflows/ci.yml) は回帰テスト・コンテナ合成確認。実収集・正本更新を証明しない。
- Pagesはmain push、毎時23分、Cloud配置Workflowのmain成功、手動dispatch等で実行。変更なしのscheduleチェックはbuild/deployを省略し得る。
- **テスト成功≠Job成功≠GCS HEAD更新≠Pages成功≠実Web一致**。コミットSHAと正式リリースのsource SHAが異なる場合も、それだけで不整合ではない。正式run ID・公開SHA・ID集合を比較する。

## エラー時の取り扱い

| 状況 | 先にすること | 絶対にしないこと |
| --- | --- | --- |
| ログイン・PDF/HTML取得失敗 | 失敗した会社/地区のmanifest・receiptとCloud Runログを確認 | 失敗会社を正常0件扱い、他情報源の募集を削除 |
| RealPro・Mansion Reviewの上流待機 | 当該週の先行execution実在・終了状態を確認 | 重複起動、上流未実行を終了扱い |
| QC・名寄せの保留/異常 | 個別の原本・evidence・reviewと一意性を確認 | 保留を一括採用、根拠なく新規建物を追加 |
| CAS競合・lease | 最新HEAD generationと稼働中Jobを再読取 | 他実行のlease消去、旧HEAD強制上書き |
| Pages未反映 | HEAD/run marker差、release_check/build/deploy/verifyを確認 | 診断目的で全社再収集 |
| 一部成功 | 成功範囲と失敗範囲を特定し旧currentを保持 | 全社完全成功と報告 |

## バックアップとロールバック

1. 更新対象の**最新**HEADとgeneration、実行中Job、既に進んだ後続リリースの有無を確認。
2. master/publicの参照世代・SHA、GCS backup、SQLite integrityと建物ID・alias・履歴・source別current・公開集計を検証。
3. 必要な対象だけ修復し、collection lease・期待generationのCASを守る。後発の正常更新を古い成果で上書きしない。
4. 復旧後は最新HEADとPagesの公開marker・JSON・ID集合・集約値まで再検証。
5. `python -m tatemono_map.cloud.republish` は収集しないが**GCSリリース/HEADを書き換える操作**。単なる調査のためには実行しない。replay・Scheduler resume・Cloud Run再配置も診断の一部にしない。

## ドキュメント変更だけの場合

- 本番SQLite、GCS HEAD、Cloud Run、Scheduler、PDF/HTML収集、Pages公開コードを触らない。
- `deploy_pages.yml`は通常main pushでもビルドを起動し、公開後のscheduler確認ステップを含む。無用な再ビルド・再収集を避けるため文書マージコミットを`[skip ci]`付きにする場合、PRテストや必須チェックを無効化せず、後続のschedule/workflow_runが独立に動くことを認識する。
- 主要6文書はそれぞれの担当情報だけ更新し、技術資料・歴史資料は[文書索引](README.md)から参照する。

## 補助資料

ローカル・手動PDF・修正CSVは[専門資料](README.md#専門資料)を参照。GitHubにある旧手順を現在の本番正本に逆流させない。
