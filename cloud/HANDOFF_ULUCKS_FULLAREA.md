# Ulucks 全業者・北九州全域 引継ぎ
更新: 2026-10-17 16:40 UTC。中断時は本書と PR #372 の最新状態を確認する。

## 保存時点
- 保存直前 main HEAD: a5961483a37474d238c8382131d193f3b26eec58。本書コミット後の正確な main HEAD は PR #372 本文に記録。
- 全業者版: draft PR https://github.com/aik38/tatemono-map/pull/372 、branch `codex/ulucks-all-companies-20261018`、HEAD `58750cc87adf8f4831e3e4a3a33286f6ff1570a5`。
- 工程①: 会社8・北九州全域の新規実取得と解析完了、名寄せで停止。正式反映未完了。工程②の実装はPR内、全業者実収集未実施。工程③の全業者週次切替未実施。
- 成功版保全済み: `backup/ulucks-initial-success-20261017` = `180bf519f52a295709f0286f3b303279981701cb`。再作成不要。

## 正式状態（変更せず保持）
- project `tatemono-map` / region `asia-northeast1` / job `tatemono-collection-poc`
- bucket `tatemono-map-poc-523194690131`
- GCS正式リリース `20261017T102111Z-18f4f7234ead`
- master SHA-256 `57f86ec174dadf58df95842862cd9a7e9be9bade9328af1a10d27e33c62fe4e6`
- public SHA-256 `b614ca1caa54ff4d6f53dca6b81e8bce75e6b4bb620d5fe5fed12d8ec1ac2e75`
- 正式建物6,982、listings 53,280、raw_sources 116,442、sale_listings 11,907。旧公開DBの行数は建物6,982・空室5,099（非表示5建物を含むため画面表示件数とは区別）。
- Pagesは従来の正常公開を維持。広域取得を公開拡張しない。PRでは既存公開DBの表示対象IDに公開を固定し、非表示ID・広域新規建物を公開DB/JSON/HTMLへ混入させない。
- Jobは失敗した会社8全域版設定・イメージを保持しており、自動ロールバックされない。Schedulerは旧設定で有効だったことまで確認済み、直近の状態は再照会が必要。全業者版は未有効化。失敗収集を0件にしない。

## 再取得不要な実績と入力
- 新規実取得run `20261017T160944Z-10bd49a595a4`。実PDF54ページ・1,045行、UI件数と解析照合済み。
- GCS `private-runs/20261017T160944Z-10bd49a595a4/pdf/000.pdf`、同prefixの `collection-evidence.json` / `ui-observation.json` / `failure.json` / `review/` を再利用。
- 実取得Actions https://github.com/aik38/tatemono-map/actions/runs/39047612139 （deploy job 117440294157）、source `6da44fd50295e3e14cc9ee4e60acc532d0eeea63`。
- 失敗理由 `ingest_unmatched_or_suspect_rows`。GCS正式HEAD・公開は保持。
- 取得済みPDFの隔離再解析 https://github.com/aik38/tatemono-map/actions/runs/39049813542 は成功。PDF再取得/ログイン/正式更新なし。
- 再解析: 新規候補88（隔離DBのみ、正式追加ではない）、unmatched172、suspect16（重複を含むため単純合算しない）。
- 内訳: close_conflicting_candidate131、address_not_granular25、address_multi_or_range14、name_suffix_conflict2、building_id_unresolved16。
- 実DOM会社一覧131行、実在物件一覧URL69業者、一覧URLなし62行（うちrequest導線4）。URLなしを空室0とみなさない。会社ID連番推測・request送信なし。北九州グループは実DOM22子地域＋親、対象外地域未選択を確認。

## 未解決・次の作業
1. `cloud/inspect_failed_acquisition.py` の暗号化私的診断を復号し、具体例に基づき保守的に名寄せを修正する。診断groupingに列名ミスあり: raw_name/raw_addressではなくname/address。unique_groups=5は物件数ではなく理由別に潰れた結果なので使わない。
2. 既存の実PDFとgeneration/SHA検証済み正式正本で再解析。曖昧な部屋・名称/住所を推測で統合しない。旧unknown所有権はpreserve_unknown。
3. 会社8全域の取得・解析・名寄せ・公開範囲検証が成功してから正式GCS更新とPagesを確認。既存ID/URL・他ソース・履歴保全を確認。
4. その後のみPR #372を最新mainに同期しCI確認、全業者実行へ進む。merge marker `ULUCKS_ALL_COMPANIES_20261018`。PR内では初回 `--prove-expansion` の全件実行成功を必要とし、成功証跡がない全業者週次実行はスキップする。
5. 全業者正式反映・Pages成功後に既存週次Schedulerを一系統へ切替・確認。月曜04:00 Asia/Tokyoが従来設定。有効化と実際の定期実行成功を分けて報告。
6. 工程完了・重要修正・失敗時、本書とPRのmain/到達点を更新する。

## 再開時の実行経路と注意
- GitHub接続＋既存Actions WIFでGCP Job/Loggingを操作。Chrome接続はHTTP401、Work cloud browserも利用不可だったため繰り返さない。IAM/WIF/環境初期構築・Secret再登録は不要。
- Secret値は表示しない。既存 `ULUCKS_LOGIN_SECRET` を維持。GitHub deployerはprivate GCS入力を直接読めない。runtimeはprefix内objectアクセス可能だがbucket list不可、権限を拡張せず既知の入力を使用する。
- 診断はruntimeが読んだ具体例を一時RSA公開鍵で暗号化しログへ出力。復号秘密鍵はscratchのみに保存。scratch消失時は新規一時鍵で同じ既取得PDFを再診断すればよく、再収集不要。
- 私的PDF/ZIP/会員情報/復号結果/秘密鍵はPublic GitHub・公開artifactに置かない。添付参考PDFは収集実績に転用しない。
- PRに全業者逐次収集・全件成功時のみCAS正式更新・公開対象ID制御・過去実URLの再確認・純粋文字列正規化キャッシュ・週次証跡ゲートを実装済み。PR未merge、正式完了ではない。
- 必須のテスト/CIは過去に成功。新しい変更に応じた検証だけ行い、調査・実収集を最初から繰り返さない。
