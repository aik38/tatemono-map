# Ulucks 全域・全業者 再開チェックポイント
更新: 2026-10-17 21:49 UTC。以下の最新チェックポイントを優先し、下段は過去の経過記録として参照する。

## 最新到達地点：工程A完了、工程B/C未完了
- 保存前main HEAD: `2a12431ca2f55d734f7393487877d6f2c75dc7e2`。PR#372はmerge済み、実行source `6dacbcc75e1dd4292b72277203cb6f0be7f5ac31`。
- 工程A実行39070843455成功。会社8の既取得54ページ/1,045行を再利用、追加PDF取得なし。採用822行（既存建物675行、新規86棟へ147行）、保留223行、異常0、重複0、保留関連の以前の募集12行を維持。
- 地域分類は全1,045行成功。市7区965行、周辺市町80行。曖昧行はprivate DB/reviewへ保持。
- 正式release `20261017T213307Z-b0e5d051d4be`。HEAD generation1792273143672260。master SHA256 `651037da41dc4f211da5cc88103f325dbd1e985dcf1a14c9f7cdc32ff0c783a1`、public SHA256 `94d3e8ce4008948928f7cdb8b709004619e8bd00baace7f528fbb91817d1f1b2`。
- 正式建物6,982→7,068、listings53,280→54,102、raw_sources116,442→117,264、sale_listings11,907不変。canonical/既存履歴/他ソース保全QC後CAS成功。
- 公開範囲は直前の表示対象6,977棟を固定維持。公開空室5,222。新規86棟は非公開。旧公開DBの6,982棟には非表示5棟が含まれるため表示件数と混同しない。
- Pages39071854350全job成功。deployログ21:43:46 UTCに `verified_release=20261017T213307Z-b0e5d051d4be`。本番検証済み。
- Scheduler enable step成功。ただし全業者版の初回成功/週次切替はこれから。月曜04:00日本時間の実際の無人定期成功は未確認。
- 工程B開発PR https://github.com/aik38/tatemono-map/pull/373 。保存時HEAD `2f27fb2684aaa58e078d3deae08636544b32096b`。旧HEAD6a6bd1eのCI成功、最新CIを確認してからmerge。
- 次はPR373 CI確認→merge title `ULUCKS_ALL_COMPANIES_20261018_INITIAL: collect the complete observed company census` で初回全業者実行。今回だけ公開確認済み会社8 snapshotを24h以内/現行HEAD/同scope pointerの厳密条件で再利用し、他社は新規実取得。週次は全社fresh。
- 現在の未解決事項：最新全業者census/実収集、会社別採用・保留、全業者の正式GCS/Pages、同revisionの週次proofは未確認。会社一覧69件は前回観察値であり次の実画面で再照合する。
- 同時起動禁止。既存実行を照会し、private company manifest/result/checkpointを再利用する。URLなし/request要求の業者に申請・0件化をしない。既知routeがrequest壁へ変わった場合は旧scopeを保持し他社更新を継続する。

## 過去の経過記録（上の最新状態を優先）
更新: 2026-10-17 21:17 UTC（日本時間 10/18 06:17）。最新のPR/Actions/GCS HEADを先に照会する。

## コードと現在工程
- 保存前main: `ad2ec5c9ef981f6456e1a7e01e5ec0ad1f432171`。開発PR: https://github.com/aik38/tatemono-map/pull/372 。
- PR保存前HEAD: da18391f6493450145bc7fd3acba38784733085b。新しいPR HEAD/mainはPR本文とファイル履歴から取得。
- **工程A未完了**: 取得済み会社8全域PDFを使う部分反映の実装・検証まで。これからCI→会社8限定の本番実行→GCS/Pagesを確認する。
- **工程B/C未完了**: 全業者の実収集・正式更新・全業者週次切替はまだ完了していない。
- merge title `ULUCKS_FULLAREA_COMPANY8_20261018` は会社8限定。保存済みPDFをexecution overrideで再利用する。常設Job引数は通常収集のまま。
- 工程AのGCS/Pages確認後のみ `ULUCKS_ALL_COMPANIES_20261018` で全業者を初回実行する。常設週次は同じrevisionの初回成功証跡がないと収集をスキップ。

## 正式正本・クラウド（20:51〜20:53 UTC 再照会済み）
- project `tatemono-map` / region `asia-northeast1` / bucket `tatemono-map-poc-523194690131`
- 正式release `20261017T102111Z-18f4f7234ead`（広域版は正式反映前）
- master SHA256 `57f86ec174dadf58df95842862cd9a7e9be9bade9328af1a10d27e33c62fe4e6`
- public SHA256 `b614ca1caa54ff4d6f53dca6b81e8bce75e6b4bb620d5fe5fed12d8ec1ac2e75`
- 正式建物6,982、listings53,280、raw_sources116,442、sale_listings11,907。旧公開DBは建物6,982・空室5,099（非表示5建物を含み画面件数とは区別）。
- Job `tatemono-collection-poc`: source `6da44fd50295e3e14cc9ee4e60acc532d0eeea63`、timeout3600s、照会時active0。
- Scheduler: ENABLED、`0 4 * * 1`、Asia/Tokyo、既存Job宛て。全業者成功の週次証跡はまだない。
- Pagesは旧成功版を保持。既存backup branch `backup/ulucks-initial-success-20261017` = `180bf519f52a295709f0286f3b303279981701cb`。再作成不要。

## 再取得しない入力・確認済み結果
- 会社8実取得run `20261017T160944Z-10bd49a595a4`、54ページ/1,045行。UI件数との照合済み。
- PDF `private-runs/20261017T160944Z-10bd49a595a4/pdf/000.pdf`
- PDF SHA256 `9879e17da1fd3ca1afcdf90cd4e7afda10f844bd8521197ae4a5be381687ae4d`
- 同prefixの `collection-evidence.json` / `ui-observation.json` / `failure.json` / `review/` を保持。
- 修正前の隔離診断: 新規候補88（正式追加ではない）、unmatched172、suspect16（重複分類あり、合算禁止）。原因 close_conflicting_candidate131、address_not_granular25、multi/range14、name_suffix_conflict2、building_id_unresolved16。
- 実会社一覧131行、一覧URL69業者、URLなし62行（うちrequest4）。0件扱い/ID連番推測/request送信は禁止。次の全業者実行で再照合。
- 再解析39068465041・ログ回収39068807368で実PDFの地域を確認: 7区965行、周辺市町73行、未分類7行。未分類は市の字を含む町名の誤判定で、修正/回帰テスト済み。本番新コードで全1,045行を再確認する。
- 解析フレーム（修正途中版、7行未分類のためそのまま正式採用しない）:
  `private-runs/20261017T160944Z-10bd49a595a4/diagnostics/20261017T205339Z-bb4307c7c28f/parsed-frame.json`
  generation1792270419755912 / SHA256 `ad6ca8ef3bcc2055eb2f0773cd86f80a36600eba8e95ea961ef11ad78ba0f754`
- 私的診断JSON:
  `private-runs/20261017T160944Z-10bd49a595a4/diagnostics/20261017T205339Z-da7c36fbfdcd/review.json`
  generation1792270419939931 / SHA256 `4d830bdd32a14a3e06b208af343010b027376c84ae7ed423326f7b89ba597a70`

## 新しい正式仕様（旧「名寄せ100%でなければ停止」を置換）
- 高確信行を採用し、曖昧行だけ内部保留。保留率による停止はしない。UI/PDF件数不一致、地域/会社混入などscopeの信頼性異常は安全停止。
- `cloud_collection_rows` が全行の原文/号室/根拠/会社/run/採用・保留・異常・重複を追跡。`unmatched_queue` とprivate CSVを利用。
- `cloud_retained_listings` で保留に関係する以前の確認済み募集を保持し、未掲載扱い/0件化を防ぐ。所有不明の旧Ulucksは引き続きpreserve_unknown。曖昧な旧号室を推測で統合しない。
- 確認済み判定は `cloud_review_decisions` に保存。private CSVのdecision/building_id/room_label/reviewerを明示し、`python -m tatemono_map.cloud.review --db PRIVATE_MASTER --decisions PRIVATE_CSV` で反映。確認済み建物ペアを他の号室/次回へ再利用し、blockは自動aliasより優先。変更履歴はraw_sourcesに追記する。
- 郡・市見出し、改行号室、第1/第3・A/B棟・ローマ数字を保護。住所だけで別名称/別棟を強制統合しない。
- 新しい正式正本は全域を保持するが、公開DBは直前の表示対象IDだけをコピー。新規/非公開地域・保留raw・review tablesを公開DB/JSON/HTMLに出さない。
- 全業者は一つのログインセッションで逐次処理。会社ごとの異常はその会社の作業コピーだけ戻し、他社の正常更新を止めない。初回の全業者成功と週次有効化/無人定期実行成功は分けて報告。
- 既存ID/名称/住所/履歴/他ソース/賃貸順位/分譲系統を保持。QC後だけ正式HEADをCAS。GCS排他leaseで重複セッションを防止。

## 次の実行・検証
1. PR最新CIを確認。ローカルではブラウザ以外173件成功、部分反映/保留の募集保全/重複/確認判定/地域回帰も成功。PR CIで実Chromium・全suite比較・containerを確認。
2. PRを会社8限定markerでmain反映。既存Actions→WIF→GCPにより保存済み原本を再取込。新runの採用/保留/異常/保持・既存285件/ID/URL・正式release/SHA/Pagesを確認。
3. 成功後に全業者markerで初回実収集。会社別原本manifest/result/checkpointはprivate GCSへ保存されるため、失敗時は実績を再取得せず参照する。
4. 全業者の失敗scopeがあれば修正し、正常scopeの更新を維持して再開。全業者成功後に週次proof・Schedulerの対象/状態を確認し、最後に本書を更新。
5. 重要な修正/失敗/工程完了で本書とPR本文を更新。利用枠の自動検知は前提にしない。

## 維持する実行経路
- GitHub接続/Actions WIFを使用。Chrome401/旧cloud browser失敗を繰り返さない。IAM/WIF/Secret初期構築・Windows再アップロード・成功版バックアップをやり直さない。
- Secretの値は表示せず既存ULUCKS_LOGIN_SECRETを利用。runtimeはprivate objectアクセス可能、bucket list不可。既知のmanifest/refをgeneration/SHA固定で読む。
- 私的PDF/ZIP/レビュー原文/秘密鍵をPublic GitHubや公開artifactに置かない。添付参考PDFは実収集実績に転用しない。

- 21:21 UTC: 公開側にも残っていたparsed=attached条件を、採用+保留+異常+重複の厳密な全行照合へ更新。公開proof/件数/QCは維持。全件保留でも偽の0件にせず、公開SQLite/markerへの保留原文混入がないことを統合テストで確認。

## 21:25 UTC 工程A本番パイプライン起動
- PR#372 latest069b90ba、CI39070480785成功、main merge `6dacbcc75e1dd4292b72277203cb6f0be7f5ac31`。
- 実行 https://github.com/aik38/tatemono-map/actions/runs/39070843455 。会社8限定、既取得原本再利用。実行中の場合は結果を先に確認し、再起動しない。
- Pagesの既存許可済みWIF経路に `cloud/read_state.py` を追加。release_checkログのCLOUD_STATE_SAFE_JSONで正式HEAD/SHA/採用・保留等を原本再解析なしで取得できる。新workflow名によるWIF拒否はIAM変更せず既存Pages経路へ移動して解消した。
- 工程A完了はGCS正式releaseとPagesの本番検証成功を確認してから。工程B/Cは引き続き未完了。
