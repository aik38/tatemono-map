# Ulucks 全域・全業者 再開チェックポイント
更新: 2026-10-18。最新main/Actions/GCS HEADを照会し、実行中なら二重起動しない。

## 今回の確定方針・進行
- 会社一覧の物件数が数値で1以上の会社のみ収集。0・空欄・削除会社の以前のrouteを再導入しない。既存snapshotは保持。対象数/IDは固定しない。
- 週次通常実行からall_company_initial_proof_required gateを廃止。前回部分成功でも全社fresh census/収集を実行する。proofは参考証跡だけ。
- 孤立した住所/対象地域異常はprivate anomalyとして隔離し旧募集を保持。全行異常、又は3行以上かつ20%超の住所異常は会社を安全停止。PDF件数不一致/会社取り違えのQCは維持。
- 会社ごとに正本のdisposable rollback。成功/部分成功/正常0件/失敗/対象外を区別。private GCSに原本、解析行、失敗時画面/DOM/エラー、active checkpointを保存。
- 一時的な取得障害だけ最大2回試行。定期収集に旧添付PDFを流用しない。
- 本改修の本番経路は通常argsで起動し、fresh PDF→QC→正式CAS→Pages照合まで継続する。完了前に新リリース成功と報告しない。

## 現在の本番実行（2026-10-18 07:48 UTC）
- PR375 merged、収集source `479ae7731ab53ea785c4f39850befe4314e6a5d5`。CI39108110378成功（新規失敗0）、本番配置39108483763成功。変更前Job設定はprivate GCSへ保全済み。
- Scheduler画面の強制実行を07:48:40 UTCに1回実施。Scheduler呼出成功、Cloud Run execution `tatemono-collection-poc-9wvnw`。実行ユーザー `tm-weekly-trigger@tatemono-map.iam.gserviceaccount.com` を実画面照合。通常Job args、旧PDF再利用指定なし。
- **同executionは07:54:50 UTC、会社8 PDF解析中のOOM/signal9で終了。正式CASなし、旧HEAD維持。** Task終了07:54:52 UTCを実画面で照合。取得原本とcompany4/6/7のcheckpointはprivate GCSに保存済み。
- 原因: UlucksParserがpdfplumberのページキャッシュをPDF全体で保持。ページごとのclose/GCに修正し、54ページ参考PDFを1045行/警告0/最大RSS102.2MiBで解析できた（参考資料は実取得実績に未算入）。Job memory2→4GiBの余裕も確保する。
- SIGKILLによる孤立leaseを停止済execution/owner/generation照合後に安全解除し、修正後は保存済み原本を検証して再利用、未取得会社はfresh取得で本番再開する。再設定・再取得を繰り返さない。
- 収集run `20261018T074956Z-3f92737cfbba`、private prefix `private-runs/20261018T074956Z-3f92737cfbba/`。16:50 JSTに131社中positive65/zero4/blank62を自動判定、会社4の新PDF6ページ94件を取得・解析。正式CASはまだ未実施。
- 新しいGCS正式リリースと今回の最終件数は未確定。直前正式リリースは下記の旧releaseを保持。
- 次回定期予定: 2026-10-19 04:00 Asia/Tokyo。未来の無人定期成功は未確認。

## メモリ修正後の再開（2026-10-18 08:25 UTC）
- PR376/main source `afdd6ceb10b7ec0497d08b5d4ff4292ccd7ddff2`。CI39110020396成功、配置39110491519成功。ページclose/GC、memory4GiB。参考54ページの旧実装RSS1668MiB→修正版102MiB、抽出1045行は一致（参考PDFは新規実績に未算入）。
- 旧OOM executionは終了/active0/lease owner `20261018T074953Z-4912cbb69333`、generation1792309793525731を照合。private backup後CAS解除済み。正式HEAD旧release維持。
- 通常Jobに本日の取得原本run `20261018T074956Z-3f92737cfbba` の検証再利用を期限2026-10-18T10:20:20.368314Zまで明示設定（最大3h制限）。期限後は必ずfresh。完了後 `ULUCKS_RECOVERY_ACQUISITION_RUN` と `ULUCKS_RECOVERY_UNTIL` の2envを削除する。
- 最初の再開execution `tatemono-collection-poc-dt85t` は認証後company_search_missingで終了（17:21:41JST）。Chrome実画面でログイン3/3を確認し、操作用Chromeのみログアウト済み。新しい認証登録や値の表示はしていない。
- 再開Schedulerは17:24:54JSTに1回起動。現在のexecution **`tatemono-collection-poc-czfhn`**、17:25:05JSTタスク開始、実行ユーザーtm-weekly-trigger。**二重起動せずこれを追跡。**
- 識別可能な再開intentは元run private prefix配下 `recovery-scheduler-intent-afdd.json` と `recovery-after-session-release-dt85t.json`。新しいrun ID/正式CAS/Pagesは未確定。

## 着手時の実環境照合（2026-10-18 07:23 UTC）
- 最新main a77379186a02db3edd82ba63450f790368224bec。PR372/373/374 merged。
- 実行中Cloud Runなし。前回nrppkは23:33:33 UTC正常終了。
- 正式release 20261017T224648Z-cfcacaf910f6、HEAD generation1792280010837543。
- master SHA256 4e7bb67c1ad3b6c81d50173e1ee1adb6fb096d7737aa501082cff8969403c540。
- public SHA256 a2a7b1f8d5690888932913e7f76d40beb9a2b910acb0edd13f0c16b1cee67abe。
- 前回69 route/52正常/13失敗/4利用申請。解析3219/採用2468/保留751、新規335、正本7403棟。過去実績と今回を混同しない。
- 前回失敗: 9/27/41/67/72/98/118/134=住所scope、11/69/102/119=見出し、39=PDF件数。最新positive censusに該当する会社だけ再試行。
- Scheduler ENABLED、0 4 * * 1、Asia/Tokyo、既存Job URI。未来の無人実行は未確認。
- 閲覧のみの状態照合Actions39076549763 attempt2、release照合39102735096。

## 保全・接続
- project tatemono-map / asia-northeast1 / Job tatemono-collection-poc / bucket tatemono-map-poc-523194690131。
- 既存Actions→WIF→GCPを使用。IAM/WIF/Secret初期構築を繰り返さない。ULUCKS_LOGIN_SECRET参照、値を表示しない。
- Scheduler即時実行権限は既存deployerにない（get/enableのみ）。Chromeの既存GCP本人セッションは接続済み。今回SCHEDULER_VERIFY mergeではJob配置のみ→既存Scheduler画面から1回強制実行→全工程を観測する。未来の月曜無人実行とは区別。
- 正式正本・バックアップ・canonical ID/URL/名称/住所/履歴・RealPro/MR/分譲を保持。公開対象IDは直前baseline固定。
- 非公開PDF/画面/解析/保留情報はprivate GCSのみ。公開GitHub/Actions artifactへ追加しない。QC後HEAD CASとleaseで同時更新を防ぐ。
- 従来の証拠・経緯はこのファイルのgit履歴を参照。古い成功環境を再構築しない。
