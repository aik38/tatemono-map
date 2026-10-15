# Ulucks: one-company cloud collector

実装対象は、ユーザー提供画面の `kitakyushu.ulucks.jp` → 会社検索 → 会社8（株式会社不動産中央情報センター）→ 小倉北区のみ →「（新）エリア・物件別で印刷」です。印刷APIのURL・パラメーターは生成しません。実際のリンクをクリックし、そのブラウザ通信を `route.fetch()` で転送して元PDFを捕捉します。inline / popup / XHRのPDFを扱い、ログインHTMLや印刷画面のスクリーンショットをPDFの代用にしません。

**現時点でGCPの認証・実画面通信・本番公開は未実証です。** スクリーンショットからはDOMのlabel/form構造までは確定できません。実画面が契約と異なれば安全に停止し、前回の正本・公開版を維持します。通常Chromeのセッション共有を前提にしません。

## 変更対象・権限・影響

初回セットアップは既定で読み取り専用です。**`--apply` だけではIAM準備に限定**し、runtime/deployer/publisher SA・WIF・公開領域の読み取り権限・既存Ulucks login Secretのruntime権限だけを用意します。正本/公開DBへの書き込み、デプロイ権限、旧SAのactAs、bucket保護変更、Scheduler変更、GitHub変数変更・dispatchは実施しません。

以下のデータ更新・本番連携は、正本照合とコードレビュー後に **`--apply --activate --reviewed-commit <レビュー済みmain SHA>`** を明示した場合だけ実施します。checkoutと実際のmainがレビュー済みSHAと一致し、追跡ファイルに変更がなく、選定正本のSHA・DB検査が成功しない限り有効化できません。既存GCS headがある場合も選定正本とのSHA一致を必須にします。

| 対象 | 変更・影響 |
| --- | --- |
| 既存 project / region | `tatemono-map` / `asia-northeast1` を再利用。必要APIのみ有効化 |
| 既存 private bucket | オブジェクト世代管理・public access preventionを有効化。既存オブジェクトを削除しない。公開IAM/ACLや非uniform構成は停止して確認 |
| 既存 Artifact Registry | 指定したDocker repositoryを再利用。作り直さない |
| `tatemono-collection-poc` | setupではイメージを変更・実行しない。初回に確認したimageと一致する場合のみGitHubが引き継ぐ。変更前の全Job設定をprivate GCSへ退避し、テスト済みimageへ更新 |
| GitHub → GCP | WIF。repository ID・owner ID・main ref・2つのworkflowを限定。SA鍵を発行・保存しない |
| 実行SA | `tm-ulucks-runtime@tatemono-map.iam.gserviceaccount.com`。Ulucksの2つのSecretと専用GCS prefixだけに権限 |
| デプロイSA | 既存Job上のRun Developer、実行SAおよび初回復元用の旧Job SA上のService Account User、既存registry上のWriter、private Job設定backupのCreator、Schedulerのget/enableのみ（project単位。下記参照） |
| Pages SA | `state/current.json` と `public/` のObject Viewerのみ。正本・PDF・Job設定のbackupを読めない |
| Scheduler | 月曜04:00 Asia/Tokyo。新規作成時は将来の時刻で作成→pause→週次時刻へ変更。初回収集成功後にGitHubがresume |
| 既存Secret | `tm-poc-gmail-token` / `tm-poc-realpro-login` は値取得・更新・削除・権限変更をしない |
| Web | 既存のテンプレート・デザイン・URL・SEO・テーマ・住所表示条件を変更しない |

セットアップ実行者には Service Usage Admin / Workload Identity Pool Admin / Service Account Admin、必要なSAへのactAs、IAMポリシー設定権限、既存bucketのStorage Admin、指定Secretの管理権限、Cloud Scheduler Admin、既存JobのRun Admin、registryのIAM設定権限、GitHubのActions変数設定・workflow実行権限が必要です。これらは**初回作業者**の権限であり、GitHub実行SAへ一括付与しません。

初回引継ぎが失敗した際に旧Job設定を復元するには、デプロイSAが**旧JobのサービスアカウントでもactAsできる権限**を必要とします。setupはその実アカウントを `rollback_service_account_act_as` として適用前に表示し、そのアカウント上のService Account Userだけを追加します。これは旧アカウントの権限でワークロードを実行可能になる影響があります。新collector SAへ旧アカウントのSecret権限をコピーせず、既存SecretのIAMや値は変更しません。

Cloud Schedulerはresource.nameによる条件をサポートするサービス一覧に含まれないため、単一Jobだけに効くIAM条件を仮定しません。デプロイSAにはプロジェクト内Schedulerの `cloudscheduler.jobs.get` / `cloudscheduler.jobs.enable` の2権限だけをcustom roleで付与し、コードでは設定した1つのJobのみを参照・再開します。他のSchedulerもIAM上は参照・再開可能になることが初回接続の権限上の影響です。作成・編集・削除・即時実行権限はありません。[IAM resource属性の対応一覧](https://docs.cloud.google.com/iam/docs/conditions-resource-attributes)、[Scheduler IAM](https://docs.cloud.google.com/scheduler/docs/access-control) を参照してください。

## 正本未確定のまま実行できる初回接続

`cloud/first_connect.sh` はPRブランチでも実行可能です。本番更新・Job実行・Secret値取得を行わず、既存GCP資産、Ulucks Secretのバージョン/状態/IAM、project内の全bucketと**過去世代を含むSQLite候補**、Cloud Shellの既存PoC配下・private入力配下を一括調査します。環境変数・HTTPヘッダー・Secret payloadは取得しません。CLIエラーの生出力は公開ログへ出しません。

必要権限は対象projectの資産メタデータ参照、IAMポリシー参照、Secret名・バージョン状態参照、bucket一覧・object一覧/取得です。Secret Accessor、Job実行、データ書き込みは不要です。Google APIが無効、権限不足、取得予算超過なら調査不完全として報告し、成功扱いにしません。

1. Cloud Shellでレビュー対象PRのcommitを独立したcheckoutへ取得します。既存PoCディレクトリを上書きしません。
2. `work/initial-input/` へ提供CSVと、Windowsから持ち込む**独立した正本候補/backup**をまとめてアップロードします。CSV名は `buildings_master.csv` / `building_key_aliases.csv`。PR checkout側の `scripts/inspect_master_candidates.ps1 -RepoPath <既存Windows repo> -ExportSnapshots` は既存Pythonを使い、元DBを変更せずWALの確定分も含む独立コピーと照合結果をPR checkoutのprivate `work/` へ保存します。既存 `data/` / `backups/` / `tmp/backups/` が既定の探索範囲です。別の保存先には `-CandidateRoots` を指定できます。Windowsへ接続できない環境では、Cloud Shellの調査だけで最新正常版を断定しません。
3. 認証済みCloud Shellで以下を1回実行します。

   ```bash
   bash cloud/first_connect.sh
   ```

   IAM準備も同じ作業で行う場合だけ、`gh auth login --web` で本人のGitHub CLIを認証し、`bash cloud/first_connect.sh --prepare-iam` を実行します。初回作業者には追加でService Usage Admin / Workload Identity Pool Admin / Service Account Admin、既存bucketと `tm-ulucks-login` のIAM設定権限が必要です。引継ぎの既存bucket/Job/registryを照合してから準備し、違う資産は作り直しません。GitHubの `CLOUD_ENABLED=true` が既に設定されていれば、権限追加による自動更新を避けるため準備を停止します。
4. `work/first-connect/report.private.json` と（IAM準備を実施した場合）`work/gcp-setup/inventory.json` をCloud Shellのダウンロード操作で取得します。Secret/PDF/DB本体をチャットへ貼り付ける必要はありません。報告書と候補本体をpublic GitHubへ保存しません。

GCS候補はgeneration指定・checksum検査でprivate `work/first-connect/candidates/` に保存します。1候補200MiB・合計1GiBの取得予算を超える場合は黙って省略せず、要確認として記録します。候補のSHA、ID fingerprint、件数、完了run、alias解決を比較し、公開DB・整合性不良・未完了current・WAL分離ファイルを除外します。名前や日時だけの自動選定はしません。**調査完了と正本確定は別の状態です。**

## 正本・コードレビュー完了後の本番有効化

このPRのコードがレビューされmainに入った後に実施します。引継ぎPR #351のPoCをそのままデプロイしません。

1. **登録済みの `tm-ulucks-login` は再登録不要です。** setupは有効なバージョンの存在とIAMだけを確認し、値を取得・表示しません。実行時のJSON契約は次の2項目です。未登録環境だけ通常Chromeの [Secret Manager](https://console.cloud.google.com/security/secret-manager?project=tatemono-map) で登録します。チャット、GitHub、Actions変数へ値を貼り付けません。既存2件は変更しません。

   ```json
   {"username":"実際のUlucksログインID","password":"実際のUlucksパスワード"}
   ```

   Cloud Runが実行時に `projects/tatemono-map/secrets/tm-ulucks-login/versions/latest` を読みます。setupが実行SAを作成し、このSecretに `roles/secretmanager.secretAccessor` を付与します。コンソールで先に作ったSecretは値を読み出さず再利用し、バージョンを追加・上書きしません。既存Secretが無効状態なら停止します。

2. 正本を照合します。添付CSV（2,249件 / alias 90件）は照合入力、添付 `public.sqlite3`（建物6,975件、listings/current/run=0）は公開派生物です。空のprivateテーブルが存在しても正本とは判定しません。`cloud/audit_master.py` とWindows用 `scripts/inspect_master_candidates.ps1` はID・alias解決・件数・currentの完了状態・ファイルSHAを読み取り専用で比較します。Windowsの既存 `data/`・backup、GCPの既存オブジェクト、Cloud ShellのPoCディレクトリを比較してください。日時や最大件数だけで自動選択しません。**真の最新正常版は、このセッションからWindows/GCPを読めないため未確定です。**

   ```powershell
   pwsh -File scripts/inspect_master_candidates.ps1 -RepoPath <既存repo> -CanonicalCsv <提供buildings_master.csv> -AliasesCsv <提供building_key_aliases.csv>
   ```

   privateな照合結果と選定した正本スナップショットを初回だけCloud Shellへ渡します。選定元を終了・checkpointし、WALを伴わないSQLiteとSHA-256を用意します。正本を公開DBやマスターCSVから新造して既存履歴を置き換える処理はありません。

3. 同じ初回作業内でCloud Shellにmainを取得し、`work/` に次を置きます（public GitHubへpushしない）。

   - `work/setup.private.json`: `cloud/setup.example.json` をコピー。`artifact_repository: AUTO` は現行Job imageが参照する既存registry、またはregion内に唯一あるDocker repositoryを選びます。複数候補で確定できない場合はprivate一覧を出して停止し、既存名を指定できます。新規作成はしません。
   - `work/collection.private.json`: `cloud/collection.example.json` をコピー。正本内で、この会社・このエリアに属する旧Ulucks listingsの **listing_key全件** を `baseline_listing_keys` に設定し、確認後 `baseline_reviewed: true` にする。該当する旧明細が本当に無い場合に限り空配列。エリアだけで他社の行を推測して所有権を移さない。
   - 選定したprivate正本。必要に応じWindowsの照合結果・canonical/alias CSVもprivate `work/` 配下へ。

   Cloud Shellの `gcloud` と `gh` は本人アカウントで認証済みにします。SA鍵やADCファイルを新しく発行する必要はありません。`gh` の初回認証が必要なら、この一連の初期作業内で完了させます。

   ```bash
   bash cloud/bootstrap.sh --config work/setup.private.json
   ```

   `work/gcp-setup/inventory.json` に既存Job image・SA、bucket保護、WIF/Scheduler、Secret**名**、GCS内DB候補のobject/generationがまとまります。Secret値は取得しません。必要なGCS候補だけ世代を指定してprivate `work/` へ取得し、`audit_master.py` でWindows候補と照合します。bucketやregistryが違う場合も、ここで既存資産を確認して設定します。

4. 表示された変更対象と権限を確認し、選定した正本のSHAと現行Job imageを指定して同じセットアップを適用します。

   ```bash
   bash cloud/bootstrap.sh --config work/setup.private.json \
     --apply --activate --reviewed-commit '<レビュー済みmain SHA>' \
     --expected-job-image '<inventoryの現行image>' \
     --collection-file work/collection.private.json \
     --master work/verified-master.sqlite3 --master-sha256 '<照合済みSHA-256>'
   ```

   `tm-ulucks-login` は手順1の既存Secretを再利用します。`tm-ulucks-config` のみ、private設定ファイルから初回登録します。再実行時にこのSecretが既に存在すれば `--collection-file` を省略して再利用します（既存Secretの変更・ローテーションはしない）。setupは既存headを上書きせず、初回だけ正本と派生publicを保存します。`CLOUD_ENABLED=true` は最後に設定し、mainの `cloud_deploy.yml` を自動実行します。

以後はCloud Shellコマンド不要です。mainのコードpush → テスト → private image → 既存Job更新 → 1回収集 → Scheduler有効化 → Pages生成・本番確認までActionsが処理します。初回の実画面契約や正本の所有範囲に不一致があれば停止し、その不一致の解消が必要です。

`collection.example.json` の `area_id=kokurakita` は内部scope識別子です。サイトの市区町村コードやAPIパラメーターを推測したものではなく、画面では「小倉北区」のlabelから実際のcheckboxを操作します。取得後は画面上の「ログアウト」を実行し、このJob自身のセッションを解放します。

## データの保護とQC

- 正本は `masters/<run>.sqlite3`、公開派生物は `public/releases/<run>/public.sqlite3`、原本PDFは `private-runs/<run>/pdf/`。役割を混在させません。
- 取得前に正本を `backups/<run>.sqlite3` へ保存。失敗時に原本正本を一切変更しません。
- 認証済みの会社ページで、エリアcheckboxのチェックが小倉北区1個だけであることを検索前後に確認。サーバーの検索応答と件数表示を確認します。
- PDF magic / ページ数 / 全ページテキスト抽出 / Parser QC / エリア / 部屋の重複 / 賃料・面積 / UI件数との完全一致を検証。
- 既存名寄せを使い、unmatched・suspectがあれば公開を停止。high confidence auto-seedは初回既定OFFで、既存名寄せのフラグで選択可能。
- 前回の対象件数から25%を超える減少は停止（private設定で上限50%まで）。**正常0件**は、正しい会社・唯一のエリアを保った2回の新しい成功検索が両方0件だった場合のみ区別して処理。PDF未取得・ログイン失敗を0件に変換しません。
- `current_ingest_snapshots.source` に `ulucks:<scope-hash>` を追加し、providerは従来どおり `ulucks`。履歴のlistingキーはrun単位で分離し、他社・他source・前回runの行を上書きしません。
- 初期の旧明細はprivateな所有範囲の設定により、対象scopeが成功した場合だけ集約対象から外します。元明細は削除しません。scopeの会社・エリア・初期所有範囲が変われば停止。
- 建物IDと既存canonical名・住所を保護。賃貸順位 Ulucks > RealPro > Mansion Review賃貸、分譲は独立したMansion Review情報源を維持。
- `publish_public.ps1` と同じ必須/任意テーブルコピー契約をPythonで実装。空室明細・raw・認証・PDFはpublicへコピーしません。簡易 `export_public_db.py` への置換ではありません。
- 全QC後にだけ `state/current.json` を **generation一致のCAS** で更新。masterとpublicの参照を1つのcommitで切替。同時実行で負けたrunは再試行して勝者を上書きしません。
- 既存Job変更前の設定をprivate prefixへ退避。収集失敗時は、Job世代が変わっていないことを確認して以前のJob設定へ戻します。外部変更と競合すれば自動復元も停止。

## Pagesと実証

既存 `deploy_pages.yml` はcloud有効時のみ、generation指定とSHA-256・テーブルallowlist・件数検査を通ったpublic DBをGCSから取得します。失敗時にリポジトリの古いDBへ暗黙フォールバックして公開しません。cloud無効時は従来の公開DB入力を維持します。

Schedulerの更新後は毎時23分の確認で未公開releaseだけを検出し、既存Pagesビルドを実行します。新releaseがなければビルドを省略。コードデプロイ直後は `workflow_run` でも接続します。Pages出力には公開集約値だけの `cloud_release.json` を添え、更新対象の建物ID・空室件数・賃料が既存JSONと一致することをビルド前後に確認します。公開後は実URLのreleaseマーカーと `/data/buildings.json` を再取得して照合します。UI自体は変更しません。

成功の記録を分離します。

1. ローカル/CI: 合成画面の実ブラウザ操作、合成PDF→既存Parser→既存名寄せ→正本→公開→既存render、失敗保護・競合・正常0件、Docker buildとコンテナbrowser。
2. 提供PDF: ユーザー提供の複数エリアPDFを既存Parserで検証。具体的な件数・エリア別集計はprivateな検証結果とチャットにのみ記録します。このファイルを投入・公開した実績とは扱いません。私有ファイルをGitへ入れず `cloud/validate_sample.py` で再検証できます。
3. クラウド: 新たに自動取得したPDF数・解析数・添付数・公開DB checksumとrelease ID。
4. 本番: Pages deploy成功後の実URLで同一releaseと対象建物データを確認。

mainには今回と無関係な既存テスト失敗があります。CIはcloud/coreの全件成功を必須とし、全体スイートは実際の変更前commitを別worktreeで実行して、新しい失敗が増えたら停止します。既存失敗のIDを固定除外せず、件数・残存失敗・修正された失敗をActions summaryへ明示します。全体テストがすべて成功したとは報告しません。
