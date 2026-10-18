# Ulucks 全域・全業者 再開チェックポイント
更新: 2026-10-18。最新main/Actions/GCS HEADを照会し、実行中なら二重起動しない。

## 今回の確定方針・進行
- 会社一覧の物件数が数値で1以上の会社のみ収集。0・空欄・削除会社の以前のrouteを再導入しない。既存snapshotは保持。対象数/IDは固定しない。
- 週次通常実行からall_company_initial_proof_required gateを廃止。前回部分成功でも全社fresh census/収集を実行する。proofは参考証跡だけ。
- 孤立した住所/対象地域異常はprivate anomalyとして隔離し旧募集を保持。全行異常、又は3行以上かつ20%超の住所異常は会社を安全停止。PDF件数不一致/会社取り違えのQCは維持。
- 会社ごとに正本のdisposable rollback。成功/部分成功/正常0件/失敗/対象外を区別。private GCSに原本、解析行、失敗時画面/DOM/エラー、active checkpointを保存。
- 一時的な取得障害だけ最大2回試行。定期収集に旧添付PDFを流用しない。
- 本改修の本番経路は通常argsで起動し、fresh PDF→QC→正式CAS→Pages照合まで継続する。完了前に新リリース成功と報告しない。

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
- Scheduler即時実行権限は既存deployerにない（get/enableのみ）。通常Job argsの手動実証と、未来のScheduler無人実行成功を分ける。
- 正式正本・バックアップ・canonical ID/URL/名称/住所/履歴・RealPro/MR/分譲を保持。公開対象IDは直前baseline固定。
- 非公開PDF/画面/解析/保留情報はprivate GCSのみ。公開GitHub/Actions artifactへ追加しない。QC後HEAD CASとleaseで同時更新を防ぐ。
- 従来の証拠・経緯はこのファイルのgit履歴を参照。古い成功環境を再構築しない。
