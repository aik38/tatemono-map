# runbook（Pages 運用）

> データの正本/入力/派生/reviewの全体像は [`docs/data_flow_and_sources_of_truth.md`](./data_flow_and_sources_of_truth.md) を先に確認してください。

## 最短運用（これだけ）

1. 空室（Ulucks/RealPro）優先の更新は `scripts/run_all_latest.ps1` で実行する。
2. `data/public/public.sqlite3` はローカル生成物として扱い、通常のPRにはバイナリ差分を含めない（必要なら `git restore data/public/public.sqlite3`）。
3. `main` への push をトリガーに GitHub Actions が `dist/` を生成し、Pages へ deploy する。

> Pages は `dist/` を配信し、`dist/` は毎回 Actions で再生成する。

---

## 役割分担

### PR1/PR2 運用整理（要点）
- 建物は残る（canonical `buildings` は削除しない）。
- 空室は sourceごとの current snapshot を合成して更新する。
- 高信頼 unmatched は auto-seed で建物追加し、低信頼は review CSV に残す。
- review CSV は主経路ではなく、異常時の例外ハンドリング出力として扱う。
- 建物名正規化は「不要空白の除去」と「末尾 I/II/III と 1/2/3 の整合確認」までの最小改善に限定し、区名矛盾・地理矛盾の救済は行わない。
- 「名前が強一致で候補1件のみ」の自動救済は、誤結合リスクが高い間は見送り、review CSV での確認を優先する。


- main DB（SoT）: `data/tatemono_map.sqlite3`
- public DB（配信用スナップショット）: `data/public/public.sqlite3`
- 公開物（Pages）: Actions で生成した `dist/`

`public.sqlite3` は main DB からの生成物として扱う。`dist/` は `.gitignore` のまま維持する。

---

## コマンド例

### Ulucks/RealPro 最新反映 → ローカル確認（一発）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$ZIP_DIR = Join-Path $REPO "tmp/manual/inputs/pdf_zips"
$SRC = if (Test-Path $ZIP_DIR) { $ZIP_DIR } else { Join-Path $env:USERPROFILE "Downloads" }
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\sync.ps1" -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_all_latest.ps1" -RepoPath $REPO -DownloadsDir $SRC -QcMode warn -SkipPush
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev_dist.ps1" -RepoPath $REPO -Port 8788
```

- ZIP 置き場は原則 `tmp/manual/inputs/pdf_zips`。無ければ `Downloads` から最新 `リアプロ-*.zip` / `ウラックス-*.zip` を使います。
- RealPro PDF は「印刷 → PDF」を避け、元PDFを「ファイル → 名前を付けて保存」で取得する（印刷PDFは no-text になり抽出不能化する場合がある）。

### 週次更新（public DB 更新まで）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$ZIP_DIR = Join-Path $REPO "tmp/manual/inputs/pdf_zips"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_all_latest.ps1" -RepoPath $REPO -DownloadsDir $ZIP_DIR -QcMode warn
```

- `weekly_update.ps1` は source / input_csv / outdir / run_id / QC結果 / snapshot切替可否 / publish_public成否 をログ出力します。
- current snapshot は source 単位で保持され、`building_summaries` は sourceごとの current snapshot を合成して空室集計します。
- `weekly_update.ps1` は QC 成功時のみ対象 source の current snapshot を切り替えます（他sourceの current は保持）。
- `publish_public.ps1` 失敗時は対象 source の current snapshot を前回値へ戻し、公開状態を壊さない運用にしています。
- review CSV（`new_buildings` / `suspects` / `unmatched_listings`）は例外処理のために維持し、通常週次では件数の異常監視を優先します。
- `new_buildings_*.csv` は auto-seed 監査ログです（`ingest_run_id` / `source_evidence_id` / `building_id` を保持）。
- 緊急停止したい場合は `python -m tatemono_map.building_registry.ingest_master_import --disable-auto-seed ...` を使用します。

### ingest + publish + commit/push（ワンショット）

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_to_pages.ps1" -RepoPath $REPO
```

### スクリプトの役割分担（要点）

- `scripts/run_all_latest.ps1`: 空室（Ulucks/RealPro）を最優先で更新。`sync` → `run_pdf_zip_latest` → 最新 `master_import.csv` を `run_to_pages` へ渡す。
- `scripts/run_pdf_zip_latest.ps1`: `Downloads` などから最新 ZIP（`リアプロ-*.zip` / `ウラックス-*.zip`）を選んで `run_pdf_zip.ps1` を呼ぶ。
- `scripts/run_pdf_zip.ps1`: ZIP 展開 → `pdf_batch_run` で `master_import.csv` を生成（戸建キーワード行は除外。完全保証ではなくキーワードベース）。
- `scripts/weekly_update.ps1`: `master_import.csv` を ingest + QC + snapshot 切替 + `publish_public` まで実行（commit/push はしない）。
- `scripts/run_to_pages.ps1`: 既存 `master_import.csv` を ingest + `publish_public` + 公開JSON更新 + commit/push。
- `scripts/mvp_refresh.ps1`: Mansion-Review / ORIENT 補助ルート。`fill_only` で building facts を補完し、doctor tri-state（OK/WARN/NG）で判定。
- `scripts/dev_dist.ps1`: `data/public/public.sqlite3` から `dist` を再生成し、Pages-like (`/tatemono-map/`) でローカルHTTP確認する。

### source_kind / snapshot の整理（実装準拠）

- `listings.source_kind` は provider 別値（例: `ulucks` / `realpro` / `mansion_review_chintai`）を保持する。
- `ingest_runs.source` と `current_ingest_snapshots.source` は運用上 `master_import` を使用する。
- `raw_sources.source_kind` は従来どおり `master` を保持する。

---

## 反映確認（必ず2段）

1) ローカル確認（Actions と同じ入力で再現）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
# dist生成 + ガード + ローカル確認（ポートは例）
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev_dist.ps1" -RepoPath $REPO -Port 8788
```

### ローカルで v2 を確認する（重要）

`file://` で dist の index.html を直接開くのは禁止です。`fetch()` の失敗や相対パス解決差異で Pages とズレます。
必ずローカルHTTPサーバ経由で確認してください。本番は custom domain の root 配信ですが、
ローカルでは `http://127.0.0.1:8788/tatemono-map/`（ポートは例）の pages-like プレビューを推奨します。

2) push 後の Pages 応答確認

```powershell
Invoke-WebRequest https://www.tatemono-map.com/index.html | Select-Object StatusCode,Headers
curl.exe -s https://www.tatemono-map.com/build_info.json
```

- `Headers.Last-Modified` / `Headers.ETag` が更新されていることを確認する。
- `run_to_pages` / `publish_public` / `dev_dist` をローカル実行しただけでは本番は変わりません。`main` push をトリガーにした Actions 完了後に Pages 応答を確認してください。
- ブラウザ確認はシークレットウィンドウで行い、必要に応じて `Ctrl+F5`。

### 住所表示モード（full / short）の運用

- 仕様（実装準拠）:
  - `full`: フロント表示は完全住所。
  - `short`: フロント表示のみ短縮住所。
  - Google Maps 埋め込み / Google Maps リンク / DB保存 / 名寄せ / correction は常に完全住所。
  - `short` の短縮は原則「市区町村 + 町名 + 丁目」まで（先頭の都道府県名を除去）。丁目が安全に取れない場合は無理に壊さない。
    - 例: `福岡県北九州市小倉北区黄金1-2-10` → `北九州市小倉北区黄金1丁目`
    - 例: `福岡県北九州市小倉北区片野3-15-2` → `北九州市小倉北区片野3丁目`

- ローカル表示確認は `render.build --address-mode full|short` を使う（repo ルートで実行）。
  - `python -m tatemono_map.render.build --db-path data/tatemono_map.sqlite3 --address-mode full`
  - `python -m tatemono_map.render.build --db-path data/tatemono_map.sqlite3 --address-mode short`
- 本番URLの切替は GitHub Actions の `Deploy GitHub Pages` を `workflow_dispatch` で起動し、`address_mode`（`full` / `short`）を選び、branch は `main` で deploy する。
- build / deploy 完了後は https://www.tatemono-map.com/ で確認し、必要に応じて `Ctrl+F5` か通常再読込を行う。
- 既定値: `workflow_dispatch` の `address_mode` 入力の default は `full`。`main` push の自動 deploy も `full` で build される。
- 役割分担（住所表示確認）:
  - ローカル確認: `render.build`
  - 本番URL切替: `Deploy GitHub Pages` の `workflow_dispatch`
  - `scripts/run_to_pages.ps1`: ingest / 公開DB更新用（今回の住所表示確認には使わない）

### 配色テーマ（ph / default / mercari）の運用

- 仕様（実装準拠）:
  - クエリなしURL（トップ / エリア / 建物詳細）は、deploy/build 時に設定した既定テーマで表示する。
  - `?theme=default|ph|mercari` が有効値なら、そのページでのみクエリ指定を最優先する。
  - `?theme=` が無い場合は deploy/build の既定テーマを使う。
  - 内部リンク（一覧→詳細リンク、パンくず、サイト内導線）は SEO 安全運用のためクエリなしURL基準で、`?theme=` を自動引き継ぎしない。
  - canonical は常にクエリなし正規URLを維持する（`?theme=` は canonical に含めない）。
  - sitemap / 内部リンク / 一覧→詳細リンク / パンくずはクエリなし正規URL基準。
  - テーマ切替は配色・クラス適用のみで、本文意味・`title` / `description` 方針は変更しない。
- ローカル表示確認（repo ルートで実行）:
  - `python -m tatemono_map.render.build --db-path data/tatemono_map.sqlite3 --theme ph`
  - `python -m tatemono_map.render.build --db-path data/tatemono_map.sqlite3 --theme default`
  - `python -m tatemono_map.render.build --db-path data/tatemono_map.sqlite3 --theme mercari`
- 本番既定テーマの切替手順:
  - GitHub Actions の `Deploy GitHub Pages` を開く。
  - `Run workflow` を押し、`theme`（`ph` / `default` / `mercari`）を選ぶ（branch は `main`）。
  - build / deploy 完了後、https://www.tatemono-map.com/ の **クエリなしURL** で反映を確認する。
- 既定値: `workflow_dispatch` の `theme` 入力の default は `ph`。`main` push の自動 deploy も `ph` で build される。
- 確認時の考え方:
  - 本番既定テーマの確認は、deploy 後にクエリなしURL（トップ/詳細）で行う。
  - `?theme=` の確認は、トップや詳細URLに直接 `?theme=...` を付けてページ単体で行う。
  - 「トップで `?theme=` を付けた後に詳細へ遷移しても同じテーマを維持する」仕様ではない。
  - `scripts/run_to_pages.ps1` は ingest / 公開DB更新用であり、今回のテーマ確認手順には不要。

---


## v2 一覧の軽量化（JSON方式）

- `python -m tatemono_map.render.build --db-path data/public/public.sqlite3 --output-dir dist --version v2` 実行時に `dist/data/buildings.json` と `dist/data/buildings.v2.min.json` を生成する。
- `dist/index.html`（v2）は `./data/buildings.v2.min.json` を優先 fetch し、404/parseエラー/必須キー不足時は `./data/buildings.json` にフォールバックする。
- 初期描画は50件、検索入力は debounce（250ms）、ヒット件数が多い場合は先頭200件まで描画する。
- 計測ログは `console.info` に `[v2][perf]` として出力される（fetch開始/response受信/JSON.parse完了/初期描画完了/検索1回の filter+render）。
- 確認時は DevTools の Network で `buildings.v2.min.json`（失敗時は `buildings.json`）が 200 で取得できるか、Elements でカードが段階描画されるかを確認する。

### gzip / br 配信の確認手順（実装変更なし）

- Chrome DevTools の Network で `buildings.v2.min.json` または `buildings.json` を選び、Response Headers の `Content-Encoding` が `gzip` または `br` になっているか確認する。
- PowerShell（Windows）例:

```powershell
curl.exe -I https://www.tatemono-map.com/data/buildings.v2.min.json
Invoke-WebRequest -Method Head https://www.tatemono-map.com/data/buildings.v2.min.json | Select-Object -ExpandProperty Headers
```

- `Content-Encoding` が見えない場合は、CDNキャッシュやプロキシ条件で変わるため、ブラウザの実レスポンスヘッダーも合わせて確認する。

---



## MVPローンチ手順（安全版）

ローンチ前の全ソース取り直しは `scripts/mvp_refresh.ps1` を正とします。以下を一発実行すると、バックアップ→Mansion-Review listfacts ingest→（任意）Orient facts ingest→publish→doctor gate まで実行します。

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\mvp_refresh.ps1" `
  -RepoPath $REPO `
  -CityIds "1616,1619,1614,1618,1620,1677,1676,1675,1681,1678,1639,1683,1641,1632,1651" `
  -Kinds "mansion,chintai" `
  -SleepSec 0.7 `
  -MaxPages 0 `
  -CreateMissingSafe:$false
```

- 出力ログに `BACKUP=...`, `OUT=...`, `DOCTOR=OK/WARN/NG` を表示します。
- `-CreateMissingSafe` を付けると Mansion-Review listfacts ingest の「安全な新規建物作成」を有効化します。
- `data/manual/orient_building_facts.csv` が存在する場合のみ、`ingest_building_facts --merge fill_only` で補完します。

### バックアップ先

- `tmp/backup/<timestamp>/data/tatemono_map.sqlite3`
- `tmp/backup/<timestamp>/data/public/public.sqlite3`
- `tmp/backup/<timestamp>/dist/`

### 復旧手順（バックアップから戻す）

```powershell
$REPO = "C:\path\to\tatemono-map"
$TS = "20260101_120000"  # 例
Copy-Item "$REPO\tmp\backup\$TS\data\tatemono_map.sqlite3" "$REPO\data\tatemono_map.sqlite3" -Force
Copy-Item "$REPO\tmp\backup\$TS\data\public\public.sqlite3" "$REPO\data\public\public.sqlite3" -Force
Remove-Item "$REPO\dist" -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "$REPO\tmp\backup\$TS\dist" "$REPO\dist" -Recurse -Force
```

### doctor gate の意味

`run_mvp_doctor.ps1` は `RESULT=OK/WARN/NG` を返します（`NG` のみ non-zero exit）。

- **NG（必須停止）**
  - duplicates（`norm_name + norm_address` / `canonical_address` の重複）
  - orphans（`listings.building_key` が `buildings` に存在しない行）
- **WARN（既定）**
  - 最新 `unmatched_building_facts_*.csv` に未解決行がある場合（Mansion-Review facts は後続の Google API enrich 前提で保留可能）
- **INFO（現状維持）**
  - `unmatched_listings_*` は件数表示のみ（ゲート判定には未使用）

`mvp_refresh.ps1` は doctor を `-UnmatchedFactsPolicy warn` で呼び出すため、facts の未解決は `DOCTOR=WARN` になります。最新の unmatched CSV パスと行数は `WARN/NG` いずれでも常に出力されます。

必要に応じて `run_mvp_doctor.ps1 -UnmatchedFactsPolicy ng|warn|ignore` を指定できます（既定: `warn`）。

### 重複建物の安全マージ

重複解消は `scripts/merge_duplicate_buildings.ps1` を使用してください。以下の「安全条件」を満たす場合のみ自動マージします。

- 片方のみ `listings_cnt > 0`（もう片方は `0`）
- または両方 `listings_cnt = 0` かつ `canonical_address` が一致、さらに `canonical_name` 正規化一致

上記以外（曖昧ケース）は **DBを変更せず**、`tmp/review/duplicate_candidates_<timestamp>.csv` を出力します。実行のたびに `tmp/review/duplicate_merge_<timestamp>.csv` も出力し、適用内容（または未適用）を監査できます。

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\merge_duplicate_buildings.ps1" -RepoPath $REPO
```

---

## Mansion-Review/Orient building facts update (fill-only)

Mansion-Review / Orient 由来の建物ファクト（構造・築年数・入居ラベル）を canonical Buildings DB に補完する運用です。Ulucks/RealPro の listing 由来データを上書きしないため、既存値保護の `fill_only` を使います。

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_mansion_review_facts_to_db.ps1" `
  -RepoPath $REPO `
  -CityIds "1616,1619,1614,1618,1620,1677,1676,1675,1681,1678,1639,1683,1641,1632,1651" `
  -Kinds "mansion,chintai" `
  -MaxPages 3 `
  -Merge fill_only
```

- このルートは Ulucks/RealPro の listing 取り込みを補完するものです。
- `fill_only` では `buildings.structure / age_years / availability_label` が空のときだけ更新します（既存値は保持）。
- 安全運用のため `MaxPages` は明示値（`>0`）を推奨します。`0` の自動ページングは誤検知する場合があります。
- 生成順: crawl facts CSV → `ingest_building_facts` → `publish_public` → `dist` JSON export（commit/push はしません）。

---


## マンションレビュー（一覧ページのみ）で分譲データ更新

> 必ず先にリポジトリへ移動してから実行してください（相対パス事故防止）。

```powershell
$REPO = "C:\path\to\tatemono-map"
Set-Location $REPO

pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_mansion_review_listfacts_to_db.ps1" `
  -RepoPath $REPO `
  -CityIds "1616,1619,1614,1618,1620,1677,1676,1675,1681,1678,1639,1683,1641,1632,1651" `
  -Kinds "mansion,chintai" `
  -SleepSec 0.7 `
  -MaxPages 0 `
  -Merge fill_only

pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\publish_public.ps1" -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev_dist.ps1" -RepoPath $REPO
```

- 取得は listfacts（city 一覧）主体です。通常は一覧ページのみを使い、address 欠損時のみ detail 補完が入ります。
- 対象 city_id は 15 エリア（`1616,1619,1614,1618,1620,1677,1676,1675,1681,1678,1639,1683,1641,1632,1651`）です。
- 分譲は「価格レンジ（平均価格）」と「販売情報件数」を public DB / dist に反映します。
- 入居可能日は `vacancy_count > 0` のときのみ表示対象です（分譲/空室0件は `—`）。
- 賃貸は Ulucks/RealPro 優先を維持し、マンションレビュー賃貸は建物facts補完として扱います。
- Batch 2（`1639,1683,1641,1632,1651`）の `created=0` は、住所抽出の汎用化・facts selector 見直し・address 欠損時 detail 補完・address coverage stats 追加で修正済みです。
- 高確信 auto-seed を有効にする場合のみ `-AutoSeedHighConfidence` を付けます（既定 OFF）。  
  ON の場合も保守的に、通常マッチで未一致のうち「建物名+住所が揃っており、正規化後も非空、既存 canonical/alias/同一正規化住所と衝突なし」のみ新規作成し、曖昧ケースは `unmatched_*` / `auto_seed_skipped_*` に残します。

---

## トラブルシュート

1. Actions の `Deploy GitHub Pages` が Success か確認。
2. `git status` で `data/public/public.sqlite3` が更新されていても生成物差分として扱う（不要なら restore）。
3. `dist/` を commit していないことを確認。
4. `https://www.tatemono-map.com/data/public/public.sqlite3` が 404 でも正常（Pages は `dist/` のみ配信）。
5. プレビューで Not Found が出る場合は、環境ルーティング由来のことがあるため上記「2段確認」を優先する。


## PR3 auto-seed のロールバック手順
1. 対象 run の `tmp/review/new_buildings_*.csv` から `building_id` を抽出する。
2. `building_sources` で同じ `source_evidence_id` を確認し、影響 listing を確認する。
3. 問題建物のみ `buildings` / `building_key_aliases` / `building_sources` を個別に戻す（既存 canonical は触らない）。
4. 次回 run は `--disable-auto-seed` で実行し、review-only 運用で再評価する。

---

## correction サブフロー標準運用（建物名崩れ・住所修正・重複 loser 公開除外）

### 1) correction とは何か（主経路との関係）

correction は、**フロント確認で見つかった例外**を安全に正本へ反映するためのサブフローです。

- 主経路: ZIP/PDF取得 → `master_import.csv` → `weekly_update` ingest → `publish_public` → Pages
- correction: 主経路で取り切れない例外（建物名崩れ・住所誤り・重複 loser 公開除外）を、`building_corrections.csv` + safe CLI で反映

主経路を壊さないため、correction は「常用の本線」ではなく**例外処理の補助線**として扱います。

### 2) correction を使う / 使わないの判断

#### 使うべきケース

- フロント表示で建物名崩れ・住所誤りを確認した
- 重複候補のうち loser を公開対象から外したい（物理削除はしない）
- 反映履歴を CSV 台帳として残したい

#### 使わない方がよいケース

- 週次の通常更新（主経路で完結する更新）
- ingest 時に出る review CSV の通常確認（`new_buildings_*` / `suspects_*` / `unmatched_listings_*`）
- `public.sqlite3` / `dist` を直接編集して一時的に見た目だけ直す運用

### 3) review CSV と correction CSV の違い

- review CSV（`tmp/review/*.csv`）:
  - ingest 実行時に生成される**主経路の例外検知出力**
  - 週次では件数監視と triage が中心
- correction CSV（`tmp/manual/building_corrections.csv`）:
  - フロント発見起点の**反映実行台帳**
  - `apply_building_corrections` で dry-run → apply の安全反映に使う

### 4) action の位置づけ（実務）

- `fix`: `field=building_name|address` を修正
- `review_duplicate`: 重複候補の記録（記録用途、即時統合しない）
- `drop_duplicate_loser`: loser を `buildings.hidden_from_public=1` にして公開対象から除外（DB物理削除しない）

> `apply_building_corrections` が実更新する action は `fix` / `drop_duplicate_loser` です。`review_duplicate` は台帳記録用途として扱います。

### 5) 標準手順（dry-run → apply）

#### Step 1. フロントで誤りを見つける

例:
- 建物名の不要空白
- 区名誤り（小倉北区 / 戸畑区など）
- 枝番不足
- 同一建物の重複（winner/loser）

#### Step 2. correction CSV に追記する

- ファイル: `tmp/manual/building_corrections.csv`
- 原則: 1行=1修正
- `review_duplicate` は候補記録（triage/台帳用途）
- loser を公開から除外したい場合は `drop_duplicate_loser` を使う

#### Step 3. dry-run（必須）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Set-Location $REPO
$env:PYTHONPATH = "src"

python -m tatemono_map.cli.apply_building_corrections --db data/tatemono_map.sqlite3 --corrections tmp/manual/building_corrections.csv
```

#### Step 4. report / duplicates を確認する

`tmp/manual/outputs/` に次のCSVが出るので、毎回確認します。

- `building_corrections_report_<timestamp>.csv`
  - `outcome` / `reason` を確認（`held` があれば理由を潰す）
- `building_corrections_duplicates_<timestamp>.csv`
  - 修正後に重複候補が出ていないか確認

PowerShell 例:

```powershell
Get-ChildItem tmp/manual/outputs/building_corrections_report_*.csv | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-ChildItem tmp/manual/outputs/building_corrections_duplicates_*.csv | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

#### Step 5. apply（問題なければ本反映）

```powershell
python -m tatemono_map.cli.apply_building_corrections --db data/tatemono_map.sqlite3 --corrections tmp/manual/building_corrections.csv --apply
```

#### Step 6. public DB を再生成する

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\publish_public.ps1" -RepoPath $REPO
```

#### Step 7. 公開JSONを再生成する

```powershell
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $py -m tatemono_map.cli.export_buildings_json --db data/public/public.sqlite3 --out dist/data/buildings.v2.min.json --format v2min
& $py -m tatemono_map.cli.export_buildings_json --db data/public/public.sqlite3 --out dist/data/buildings.json --format legacy
```

#### Step 8. ローカル確認（Pages-like）

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev_dist.ps1" -RepoPath $REPO -Port 8788
```

- `http://127.0.0.1:8788/tatemono-map/` で確認する（`file://` 直開き禁止）。

#### Step 9. 差分確認と commit/push

```powershell
git status -sb
git add tmp/manual/building_corrections.csv
git commit -m "ops: apply building corrections safely"
git push
```

- `main` への push をトリガーに Actions が Pages を更新する。
- `public.sqlite3` や `dist` は生成物であり、**手編集しない**。必要がなければコミットにも含めない。

#### Step 10. 本番WEBで確認

```powershell
Invoke-WebRequest https://www.tatemono-map.com/index.html | Select-Object StatusCode,Headers
curl.exe -s https://www.tatemono-map.com/build_info.json
```

- シークレットウィンドウで実画面確認する。
- 必要に応じて `Ctrl+F5`。

### 4) ローカル確認と本番確認の違い（明示）

- ローカル確認（Step 8）:
  - 目的: 修正内容・表示崩れ・導線の即時確認
  - 対象: ローカルの `dist/` と `data/public/public.sqlite3`
- 本番確認（Step 10）:
  - 目的: Actions経由のデプロイ結果確認
  - 対象: GitHub Pages 実配信物（CDN / キャッシュ条件を含む）

両方が通って初めて「反映完了」です。

### 5) duplicate loser 公開除外の位置づけ

- duplicate loser の処理は「削除」ではなく「公開除外」です。
- `drop_duplicate_loser` は `hidden_from_public=1` を設定し、正本DBの建物履歴は維持します。
- 既存の運用思想（建物は消さない / 空室のみ更新）を崩さない範囲で公開品質を調整します。

### 6) 実例（今回の運用で実施済み）

- winner/loser 例: `ニューシティアパートメンツ南小倉II`
  - loser 行を `action=drop_duplicate_loser` で適用し、`hidden_from_public=1` に設定
  - 正本DBには残しつつ、public出力から除外
- 住所修正例:
  - `ザ・サンパーク小倉駅タワーレジデンス`
  - `CITRUS TREE`
  - いずれも `action=fix` / `field=address` で正規フロー反映

> 詳細なCSV列仕様・記入ルールは runbook ではなく仕様書（`docs/building_corrections_csv.md`）を正とします。
