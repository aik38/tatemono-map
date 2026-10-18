# Ulucks 全域・全業者：通常週次運用への復旧完了
更新: 2026-10-18 13:22 UTC / 日本時間22:22。過去の診断・経緯は本ファイルのgit履歴を参照。

## 確定した本番コードと実行
- 本番コード: `c4c378bff13ae2c80c72c7df424baa1fc5b54bf5`（PR #378）。PR #377の見出し正規化・分割PDF解析もmain反映済み。
- PR #377 CI: https://github.com/aik38/tatemono-map/actions/runs/39127568767
- PR #378 CI: https://github.com/aik38/tatemono-map/actions/runs/39129321683
- 最終本番配置: https://github.com/aik38/tatemono-map/actions/runs/39129844561
- 必須検証・全体回帰比較・コンテナ/Chromium確認成功。既存の全体suite失敗20件に新規失敗なし。無関係な失敗は今回の対象外。
- Scheduler強制実行: 2026-10-18 13:11:57 UTC。Cloud Run `tatemono-collection-poc-pb4m9`、起動元 `tm-weekly-trigger@tatemono-map.iam.gserviceaccount.com`。13:12:19開始、13:14:45正常終了。
- **これは手動で強制起動したScheduler経路の実績。月曜04:00の無人定期実行の成功実績とは区別する。**

## 最新正式正本・公開
- project `tatemono-map` / region `asia-northeast1` / Job `tatemono-collection-poc`
- bucket `tatemono-map-poc-523194690131` / 正式HEAD `state/current.json`（generation `1792329282447313`）
- 正式release: `20261018T131235Z-5ac1145986ff`、QC passed。
- master: `masters/20261018T131235Z-5ac1145986ff.sqlite3`
  - generation `1792329282085352`
  - SHA256 `8775b879304c1f772084c0aea5dd7be605bc93fa76b87066fb8a794ed9041753`
- public: `public/releases/20261018T131235Z-5ac1145986ff/public.sqlite3`
  - generation `1792329282371980`
  - SHA256 `c8c089be5dea1569fd93427b10b5f39757874984025dd23d38e6bcaeb85abf61`
- 正本: 建物7,556、listings58,862、raw_sources122,031、sale_listings11,907。
- 今回引継ぎ時の7,492棟から+64棟。直前中間成功版7,552棟から最終runで+4棟。分譲11,907件は維持。
- 公開対象6,977棟は固定したまま。公開空室5,922件。public実体の世代/SHAとSQLite quick_checkを照合済み。
- 最終Pages: https://github.com/aik38/tatemono-map/actions/runs/39130865166 （workflow_dispatch）
- 本番 `https://www.tatemono-map.com/cloud_release.json` のrelease・source_commit・public SHA・集計値と、Pagesの生成物/実Web proofを照合済み。
- 変更前の正式DBバックアップ、世代CAS、SHA検査、排他lease、会社単位rollbackを維持。元PDF・checkpoint・診断・保留原文はprivate GCSだけに保存。

## 会社・明細の確定結果
- 最新censusは131行中、物件数が数値で1以上の65社を動的選択。会社数・IDは固定していない。
- 正常処理64社（明細保留を含む）、技術的失敗0社、会社全体を元データ異常で停止した会社0社。
- 会社16は `access_request_required` のまま。利用申請は送らず、正常0件扱いもしない。
- 最終runは正常61社の有効な正式結果を世代/SHA・current snapshot・鮮度で検証して再利用。69/102/119の新しいPDF3件だけを取得。
- 解析4,139 = 採用3,114 + 保留1,004 + 異常20 + 重複1。保留と異常は非公開のまま。採用件数を増やすための推測はしていない。

| 会社ID | 解析 | 採用 | 保留 | 異常 | 結果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 11 | 75 | 66 | 9 | 0 | 正式反映 |
| 39 | 337 | 219 | 117 | 1 | 検索337件と厳密一致、正式反映 |
| 69 | 14 | 7 | 7 | 0 | 新規PDF取得・正式反映 |
| 102 | 3 | 1 | 2 | 0 | 新規PDF取得・正式反映 |
| 119 | 4 | 3 | 1 | 0 | 新規PDF取得・正式反映 |
| 16 | — | — | — | — | 利用申請が必要、取得しない |

## 最小修正の内容
- PR #377: 観測した会社見出しと比較対象の両方をNFKC/空白正規化。会社39の分割表は、同一ページの直前header-only表と単一行の実際の列境界が一致し、必須項目を備える場合だけ回復。検索/PDF件数QCは維持。
- 最初の復旧 `20261018T124742Z-bce0c7725467` で11・39成功、61社の成果を正式保存。69/102/119は当初の見出し問題とは別にログイン画面へ戻されていた。
- PR #378: 観測した同一originのルートに一意な可視password fieldがあるときだけ、既存Secretで1バッチ最大1回の再認証。未知の転送先・不明なフォーム・繰返す認証失敗は隔離。会社routeと会社/PDF identityのQCは維持。
- 最終復旧で69/102/119も成功。成功会社を再収集し直す変更や、会社ごとの特例は追加していない。

## 通常週次設定と残る実証
- Scheduler `tatemono-ulucks-weekly`: ENABLED、`0 4 * * 1`、`Asia/Tokyo`。既存Cloud Run Jobのrun API宛て。
- 常設args: `-m tatemono_map.cloud.run`。collection_mode `all_companies`、area_id `kitakyushu`、北九州22子エリア。
- 通常週次はfresh census・新しいPDF取得。以前のpartial releaseやrevisionのproofは収集開始の必須gateにしない。
- **復旧専用3環境変数は全削除・再照合済み**:
  `ULUCKS_RECOVERY_ACQUISITION_RUN` / `ULUCKS_RECOVERY_SUCCESSFUL_RELEASE` / `ULUCKS_RECOVERY_UNTIL`
- 削除前Job設定backup: `deployment-backups/normal-weekly-20261018T131556Z.json`。既存IAM/WIF/Secretは再構築していない。
- Pagesは既存の毎時23分チェックがGCSの正式release変更を検出して自動公開する。変更なしのscheduleでは重いビルドを省略する。
- **次回予定は2026-10-19（月）04:00 JST。保存時点では未来であり、無人定期実行の実証待ち。**
- 次回確認は、Schedulerの実際の定刻起動→Cloud Run終了→正式HEAD→Pages→実Webを観測する。確認目的だけの手動再収集はしない。
- プログラム側の既知の未解決失敗は0。保留1,004明細/異常20明細の精査、会社16の利用申請、追加建物公開は今回の対象外。

## 保護する範囲
- canonical建物ID・URL・名称・住所・履歴、RealPro/Mansion Review/分譲データを保護。
- 既存の未公開424棟、過去差分91棟、今回増えた正本建物を追加Web公開しない。公開ID制限は維持。
- UI/SEO/デザイン、他ソースの収集、半自動レビュー機能は今回変更していない。
- 再開時は最新main・GCS正式HEAD・Cloud Run active・Pagesを先に照合。動作中のジョブを二重起動せず、既存の成功成果・認証・環境を再作成しない。
