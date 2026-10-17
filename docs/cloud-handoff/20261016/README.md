# GCP PoC引継ぎ（2026-10-16 JST）

## このブランチの範囲

Workが既存PoCの保存済みコードを保全した引継ぎブランチです。本体コード開発はChrome経由のCodexに一本化します。この追加で収集・DB更新・公開が完成したとは扱いません。main、本番データ、既存Pagesワークフローは変更していません。

- 確認時main: `ef8ad263f47eb54bb53fd5903ba93b32b838bb38`
- 変更前バックアップ: `backup/pre-cloud-handoff-20261016`
- PoC保存コード: [poc.py](poc.py)
- 元ファイル保存日時: 2026-10-15 11:57:37 UTC
- 元ファイル: 26,785 bytes / 469 lines
- SHA-256: `f21359884a1ffde31cf400efb20940312e56cd4d534992fb16067f25b92991da`
- Python構文検査: 合格。GCPでの再実行はしていません。
- 秘密値、会員HTML、PDF、認証トークンは含めていません。

**この保存コードと、現在GCPに配置されているコードとの一致は未確認です。** GCPへ接続できた担当が既存の稼働版・Cloud Shell上の差分を確認し、後続修正を失わないようにしてください。保存コードをそのまま上書きデプロイしないでください。

## 既存GCP資産

以下はユーザー指示による引継ぎ情報です。今回GCPのライブ状態は確認できていません。

- project: `tatemono-map`
- region: `asia-northeast1`
- job: `tatemono-collection-poc`
- Cloud Shell作業場所: `$HOME/tatemono-cloud-poc`
- 保存済みPoCの既定bucket: `tatemono-map-poc-523194690131`（実際の環境変数による上書き有無は未確認）
- コードが参照するSecret名: `tm-poc-realpro-login` / `tm-poc-gmail-token`。値は取得していません。
- ユーザー報告ではCloud Build・静的契約テスト・Cloud Run初回起動は成功済み。成功済み初期構築を無条件にやり直さないこと。

WorkのGCPコンソールは `Site Unavailable / Unable to access this site.` で、1回再読込後も同じ状態でした。ログイン画面まで到達していません。ローカル実行環境にはgcloud・ghコマンドがなく、GCP用コネクタも公開されていません。認証情報の誤りやGCP障害と断定できる証拠はありません。

## 保存コードから確認できる未完成範囲

- `fetch_ulucks` はGmail中のSmartlinkを対象にHTMLを最大2ページ取得・解析する処理です。管理画面ログイン・管理会社/エリア指定・PDF出力処理ではありません。
- `do_site_probe` はRealProのログインと会社一覧の確認までです。`pdf_count=0` を返すコードで、PDF取得済みという意味はありません。RealPro認証調査は保留してください。
- `parse_pdf` は既存の `UlucksParser / RealproParser / qc_check / write_master_import_csv` を利用しますが、正本DBへ取り込みません。
- `preflight` 成功はimport確認です。実データ取得成功ではありません。
- PoCは `production_db_write=False` / `github_publish=False` の設計です。
- 一部の取得未完了statusでも終了コード0になり得ます。Cloud Runの成功終了だけで収集成功と判定しないでください。

## mainで確認した再利用先

| 処理 | 既存資産 |
| --- | --- |
| PDF解析・QC・CSV | `src/tatemono_map/cli/pdf_batch_run.py` のUlucksParser等 |
| 建物名寄せ・既存取り込み | `src/tatemono_map/building_registry/`、`src/tatemono_map/cli/master_import.py` |
| スキーマ・優先順位 | `src/tatemono_map/db/schema.py` |
| 正本運用契約 | `docs/data_flow_and_sources_of_truth.md` |
| 公開DB生成 | `scripts/publish_public.ps1` |
| Pages生成・公開 | `.github/workflows/deploy_pages.yml` |

正本は既存契約上 `data/tatemono_map.sqlite3`、canonical入力は `data/canonical/buildings_master.csv` です。GitHubツリーに正本SQLite・canonical入力CSVの実体はなく、公開派生DB `data/public/public.sqlite3` があります。これを正本の代わりに使用しないでください。最新正常版の所在・内容・整合性・IDを確認して初回移管する必要があります。

`scripts/export_public_db.py` はbuilding_summariesのみを書き出す実装です。`publish_public.ps1` が扱うbuildings等の公開DB要件と同等とみなして差し替えないでください。

現在の `current_ingest_snapshots` の主キーはsource単独で、管理会社・エリア用の列はありません。1社分の更新で他社の正常スナップショットを置き換えないよう、既存参照処理と整合する最小拡張が必要です。

Pagesはmainのpush / workflow_dispatchで起動し、リポジトリ内の公開DBからサイトを生成します。GCSからの検証済み成果物取得やGCPコードデプロイの処理は、このmainのワークフローにはありません。

## 次に使う環境・作業・完成条件

| 担当環境 | 作業 | 完成条件 |
| --- | --- | --- |
| GCPへ接続可能なWork | 既存Job設定・実行履歴・Build・作業ディレクトリ差分・private保存先を取得。Secret値は表示しない。GitHubとの初期接続を整備 | 実稼働コードと設定の引継ぎが確認でき、GitHubから既存GCPへ反映できる |
| Chrome経由Codex | このブランチの保存コードとmain既存機能を参照し、Ulucksの管理画面PDF取得、対象範囲別成功管理、SQLite永続化・QC・公開受け渡しを実装・テスト | 1社の真正PDFを自動取得し、canonical ID維持・取得失敗時の前回データ保持を確認できる |
| GitHub Actions + GCP | テスト済みコードをデプロイし、実データ取得から正本更新・公開DB生成・Pages公開・本番確認を実行 | データ変更が本番Webで確認でき、PDF数・解析数・DB結果・デプロイ結果を実測報告できる |

Ulucks/RealProの利用承諾は取得済みです。許諾取得の議論は再開しません。賃貸優先順はUlucks > RealPro > Mansion Review賃貸、Mansion Review分譲は別系統を維持します。

通常チャットとCloud Shell間のコマンド・ログの手運びは再開しません。WorkとCodexによる本体コードの二重編集も行いません。
