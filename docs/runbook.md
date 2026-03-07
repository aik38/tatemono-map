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
- `scripts/mvp_refresh.ps1`: Mansion-Review / ORIENT 補助ルート。`fill_only` で building facts を補完し、doctor tri-state（OK/WARN/NG）で判定。
- `scripts/dev_dist.ps1`: `data/public/public.sqlite3` から `dist` を再生成し、Pages-like (`/tatemono-map/`) でローカルHTTP確認する。

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
必ずローカルHTTPサーバ経由で確認してください。GitHub Pages の base path は `/tatemono-map/` なので、
`http://127.0.0.1:8788/tatemono-map/`（ポートは例）で確認できる pages-like プレビューを推奨します。

2) push 後の Pages 応答確認

```powershell
Invoke-WebRequest https://aik38.github.io/tatemono-map/index.html | Select-Object StatusCode,Headers
curl.exe -s https://aik38.github.io/tatemono-map/build_info.json
```

- `Headers.Last-Modified` / `Headers.ETag` が更新されていることを確認する。
- ブラウザ確認はシークレットウィンドウで行い、必要に応じて `Ctrl+F5`。

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
curl.exe -I https://aik38.github.io/tatemono-map/data/buildings.v2.min.json
Invoke-WebRequest -Method Head https://aik38.github.io/tatemono-map/data/buildings.v2.min.json | Select-Object -ExpandProperty Headers
```

- `Content-Encoding` が見えない場合は、CDNキャッシュやプロキシ条件で変わるため、ブラウザの実レスポンスヘッダーも合わせて確認する。

---



## MVPローンチ手順（安全版）

ローンチ前の全ソース取り直しは `scripts/mvp_refresh.ps1` を正とします。以下を一発実行すると、バックアップ→Mansion-Review listfacts ingest→（任意）Orient facts ingest→publish→doctor gate まで実行します。

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\mvp_refresh.ps1" `
  -RepoPath $REPO `
  -CityIds "1616,1619" `
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
  -CityIds "1616,1619" `
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
  -CityIds "1616,1619" `
  -Kinds "mansion,chintai" `
  -SleepSec 0.7 `
  -MaxPages 0 `
  -Merge fill_only

pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\publish_public.ps1" -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev_dist.ps1" -RepoPath $REPO
```

- 取得元は city 一覧ページ（`/mansion/city/...`, `/chintai/city/...`）のみです。詳細ページには入りません。
- 分譲は「価格レンジ（平均価格）」と「販売情報件数」を public DB / dist に反映します。
- 入居可能日は `vacancy_count > 0` のときのみ表示対象です（分譲/空室0件は `—`）。
- 賃貸は Ulucks/RealPro 優先を維持し、マンションレビュー賃貸は建物facts補完として扱います。

---

## トラブルシュート

1. Actions の `Deploy GitHub Pages` が Success か確認。
2. `git status` で `data/public/public.sqlite3` が更新されていても生成物差分として扱う（不要なら restore）。
3. `dist/` を commit していないことを確認。
4. `https://aik38.github.io/tatemono-map/data/public/public.sqlite3` が 404 でも正常（Pages は `dist/` のみ配信）。
5. プレビューで Not Found が出る場合は、環境ルーティング由来のことがあるため上記「2段確認」を優先する。


## PR3 auto-seed のロールバック手順
1. 対象 run の `tmp/review/new_buildings_*.csv` から `building_id` を抽出する。
2. `building_sources` で同じ `source_evidence_id` を確認し、影響 listing を確認する。
3. 問題建物のみ `buildings` / `building_key_aliases` / `building_sources` を個別に戻す（既存 canonical は触らない）。
4. 次回 run は `--disable-auto-seed` で実行し、review-only 運用で再評価する。
