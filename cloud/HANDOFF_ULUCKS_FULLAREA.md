# Ulucks 全域・全業者 再開チェックポイント
更新: 2026-10-17 22:39 UTC。保存値を決め打ちせず最新main/Actions/GCS HEADを先に照会する。実行中なら二重起動しない。

## 現在地点
- 工程A（会社8全域の部分反映/GCS/Pages）は完了。工程Bは実画面差分を修正し本番再開中。工程C（全社初回proof後の週次確立）は未完了。
- 保存前main/source: `9b50d79351da81f37fd1550f2b580f355044c30f`。PR372/373/374はmerged。
- 最新PR374 HEAD `9398fdb86e9604ea2c32e1e312726b815b4fee61`、CI39075498040成功（必須/core・全suite新規失敗なし・コンテナブラウザ）。
- 新Cloud Run execution `tatemono-collection-poc-nrppk` は2026-10-17 22:46:37 UTC開始、run `20261017T224648Z-cfcacaf910f6`。22:47:19に実Job source9b50d793/all_companies/kitakyushu/通常args/task1/parallelism1/retry0/21600秒を照合。
- 新runでも一覧131行/69 lists URLを確認。会社2/3は既知の許可申請案内としてcompany_unavailable記録済み。会社4は保存済み95行PDFを再解析中。正式HEAD/Pagesはまだ工程A、全社完了とは報告しない。
- 新runの原本・manifest/result/checkpointは `private-runs/20261017T224648Z-cfcacaf910f6/` 配下。二重起動せず、この実行結果とprivate company結果から再開する。
- 再開本番Actions: https://github.com/aik38/tatemono-map/actions/runs/39075913827 。この結果とCloud Run実行中の有無を先に確認。新run IDは上記。
- 初回再開だけ公開確認済み会社8scopeと旧全社runの取得済みPDFを再利用。通常週次は全社fresh。marker `ULUCKS_ALL_COMPANIES_20261018_RECOVER_FORMS` は今回のみ。
- GCP project `tatemono-map` / region `asia-northeast1` / bucket `tatemono-map-poc-523194690131` / Job `tatemono-collection-poc`。
- Schedulerは実照合でENABLED、`0 4 * * 1`、Asia/Tokyo、同Job。Jobは全社/kitakyushu・task1/parallelism1/retry0/timeout21600。新sourceの全社初回proof前は週次収集をスキップ。実際の無人定期成功は未確認。

## 現在の正式GCS・本番Pages（工程A）
- release `20261017T213307Z-b0e5d051d4be`、HEAD generation1792273143672260、source `6dacbcc75e1dd4292b72277203cb6f0be7f5ac31`。
- master `masters/20261017T213307Z-b0e5d051d4be.sqlite3`
  SHA256 `651037da41dc4f211da5cc88103f325dbd1e985dcf1a14c9f7cdc32ff0c783a1`。
- public `public/releases/20261017T213307Z-b0e5d051d4be/public.sqlite3`
  SHA256 `94d3e8ce4008948928f7cdb8b709004619e8bd00baace7f528fbb91817d1f1b2`。
- 会社8：54ページ/1,045行、採用822（既存建物675行・新規86棟へ147行）、保留223、異常/重複0、旧募集12行保持。7区965行/周辺市町80行、未分類0。
- 正式建物6,982→7,068、listings53,280→54,102、raw_sources116,442→117,264、sale_listings11,907不変。既存canonical/履歴/他ソース保全QC後CAS。
- 公開は直前の表示対象6,977棟を固定、空室5,222。新規86棟は非公開。旧公開DB6,982棟には非表示5棟が含まれるため表示件数と混同しない。
- Pages39071854350成功、deployログ21:43:46 UTCに `verified_release=20261017T213307Z-b0e5d051d4be`。後の隔離診断でも正式HEAD不変を確認。

## 解消済みの全社初回失敗と再利用する原本
- 旧全社run `20261017T220240Z-17086bbe5dd5` / execution `tatemono-collection-poc-9t6dt` は22:12:57停止済み。正式反映なし。孤立lease generation1792274558652523は対象owner照合/CAS解除済み。
- 実一覧131行中69社にlists URL、62行はrouteなし（request4含む）。69は閲覧可能数の確定値ではない。
- 実DOM診断39075168508成功：会社6検索後、次の会社26では検索欄全体が閉じる。実見出しクリックで開き、北九州全域717件の検索を確認。全22子エリア/対象外非選択は毎回検証する。
- 会社2/3はフォームなしで同じ43字の許可申請案内（sha256 cbd17c56ae8a2538ec479ba3896c1d0255f145ee5ac49846e72221e4f201af00）。既知案内だけ利用不可として証拠を保存、旧scope維持。申請しない/0件にしない。未知空画面は失敗扱い。
- 会社4は新規PDF1/6ページ/95行取得済み。2行だけ郡省略の芦屋町。公式の一意な郡を取得住所へ補完する修正済み（canonical住所は変更しない）。
- 原本/manifest：`private-runs/20261017T220240Z-17086bbe5dd5/company-{id}-manifest.json` と `companies/{id}/pdf/*.pdf`。catalog/result/checkpointも同prefix。新コードはgeneration/SHA/会社/route/22エリア/件数/24h内を確認し再解析する。保存原本なしの会社だけ実取得。
- 実診断ref：`private-runs/20261017T220240Z-17086bbe5dd5/diagnostics/20261017T222922Z-76a2c373359c/control-report.json`、generation1792276162263032、SHA256 c0132f202d1dffb9518d2faf29ac88ed54479fd2887374c96e660c8b123631a1。
- 工程Aの元PDFは `private-runs/20261017T160944Z-10bd49a595a4/pdf/000.pdf`、SHA256 9879e17da1fd3ca1afcdf90cd4e7afda10f844bd8521197ae4a5be381687ae4d。参考ZIP/PDFを実績へ流用しない。
- 隔離診断regexのescape誤りは修正済み。過去の失敗/修正経過は本ファイルのgit履歴を参照し、再調査を繰り返さない。

## 次に実行すること
1. 上記Actions/Cloud Runの結果を観測。会社別原本/manifest/result/checkpointはprivate GCSへ保存される。正常scopeは反映し、保留・利用不可・失敗を区別する。
2. 最新正式HEADをPages release_checkの `CLOUD_STATE_SAFE_JSON` から取得。全社対象数、実取得/再利用PDF、解析/採用/保留、重複、新規棟数、SHAを記録する。
3. 失敗会社があれば保存済み原本から修正再開。初回の実収集可能な全社が成功するまで週次proof完了とはしない。既知の許可申請表示は取得失敗/0件にせず別記する。
4. 正式CAS後は監視workflow rerunを止め、最後のPages公開をキャンセルしない。Pages deployの `verified_release` とSchedulerの同Job/全社source/月曜04:00JSTを確認。Scheduler有効化と無人定期実行成功を分けて報告。
5. 工程完了/重要失敗時に本書を簡潔に更新。

## 保全と運用
- 高確信のみ採用、曖昧行はprivate `cloud_collection_rows`/`unmatched_queue`/CSVへ。保留率の停止閾値なし。件数/地域/会社混入等scope全体の信頼性異常は停止。
- 保留に関連する旧募集は `cloud_retained_listings` で維持。所有不明旧Ulucksはpreserve_unknown。既存ID/URL/canonical/履歴、他ソース、Ulucks>RealPro>MR賃貸、別系統の分譲を保全。
- 確認CSVは `python -m tatemono_map.cloud.review --db PRIVATE_MASTER --decisions PRIVATE_CSV`。明示reviewerのmatch/blockを `cloud_review_decisions` と履歴へ保存、次回に再利用。未確認の推測を正解学習しない。
- 非公開範囲・保留原文・review tablesを公開SQLite/JSON/HTMLに出さない。公開対象IDは現在のbaseline固定。GCS正式HEADはQC後CAS。7h leaseと実行重複チェックを維持。
- 接続済みChrome401/旧cloud browser失敗を繰り返さず、既存Actions→WIF→GCPを使う。ローカル実行環境は現在無応答だがクラウド経路で作業継続可能。
- IAM/WIF/Secret初期構築・Windows同期・成功バックアップを再作成しない。既存login Secret参照を維持し、値を表示しない。backup branch `backup/ulucks-initial-success-20261017`=`180bf519f52a295709f0286f3b303279981701cb` は確認済み。
- ZIP/原本/レビュー原文/秘密鍵をPublic GitHubや公開artifactへ置かない。バケットlist権限に依存せずmanifestのgeneration/SHA参照を辿る。
