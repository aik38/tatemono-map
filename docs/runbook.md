# runbook（Pages 運用）

## 最短運用（これだけ）

1. `scripts/weekly_update.ps1` か `scripts/run_to_pages.ps1` で **`data/public/public.sqlite3` を更新**する。
2. Git では **`data/public/public.sqlite3` だけ** commit/push する（`dist/` は commit しない）。
3. `main` への push をトリガーに GitHub Actions が `dist/` を生成し、Pages へ deploy する。

> Pages 配信の正本入力は `data/public/public.sqlite3`。`dist/` は毎回 Actions で再生成する。

---

## 役割分担

- main DB（SoT）: `data/tatemono_map.sqlite3`
- public DB（配信用スナップショット）: `data/public/public.sqlite3`
- 公開物（Pages）: Actions で生成した `dist/`

`public.sqlite3` はリポジトリで追跡する。`dist/` は `.gitignore` のまま維持する。

---

## コマンド例

### 週次更新（public DB 更新まで）

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\weekly_update.ps1" -RepoPath $REPO
```

### ingest + publish + commit/push（ワンショット）

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_to_pages.ps1" -RepoPath $REPO
```

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

- 出力ログに `BACKUP=...`, `OUT=...`, `DOCTOR=OK/NG` を表示します。
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

`run_mvp_doctor.ps1` は以下がゼロであることを必須にします。

- duplicates（`norm_name + norm_address` / `canonical_address` の重複）
- orphans（`listings.building_key` が `buildings` に存在しない行）
- unmatched（最新 review CSV の `unmatched_listings_*` と `unmatched_building_facts_*` の行数）

`unmatched` は誤結合リスクが高いため、自動統合しません。`mvp_refresh.ps1` の最後の doctor gate で `unmatched_building_facts_*.csv` の最新ファイルに1件でも未解決行があれば `DOCTOR=NG` で停止し、unmatched CSV は安全のためそのまま残します。必ず review CSV を人手で確認してから次の更新へ進めてください。

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
2. `git status` で `data/public/public.sqlite3` が commit 済みか確認。
3. `dist/` を commit していないことを確認。
4. `https://aik38.github.io/tatemono-map/data/public/public.sqlite3` が 404 でも正常（Pages は `dist/` のみ配信）。
5. プレビューで Not Found が出る場合は、環境ルーティング由来のことがあるため上記「2段確認」を優先する。
