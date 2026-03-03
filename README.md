# tatemono-map

## 現状の正解（先にここだけ確認）

- ローカル検証は **HTTP のみ** です。`file://` で `dist/index.html` を直開きしないでください。
- ローカルプレビューは **`scripts/dev_dist.ps1` を唯一の入口** とします。
- `scripts/dev_dist.ps1` は `/tatemono-map/` プレフィックスで配信するため、GitHub Pages と同じパス条件で確認できます。

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
git -C $REPO rev-parse --is-inside-work-tree
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev_dist.ps1" -RepoPath $REPO -Port 8788
```

- ポート番号は固定ではありません（`8788` は例）。
- `file://` 直開きは `fetch` / 相対パス / ルーティング検証が Pages とズレるため禁止です。


## フロント配色テーマ切替（静的・クエリ指定）
### 本番（GitHub Pages）
- default（現行互換）
  - https://aik38.github.io/tatemono-map/?theme=default
- ph（黒 + 白 + オレンジ）
  - https://aik38.github.io/tatemono-map/?theme=ph
- mercari（赤/青/白/黒）
  - https://aik38.github.io/tatemono-map/?theme=mercari

### ローカル（dev_dist.ps1 起動後）
- default
  - http://127.0.0.1:8788/tatemono-map/?theme=default
- ph
  - http://127.0.0.1:8788/tatemono-map/?theme=ph
- mercari
  - http://127.0.0.1:8788/tatemono-map/?theme=mercari

## 開発同期（GitHub↔ローカル）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\sync.ps1" -RepoPath $REPO
git -C $REPO status -sb
git -C $REPO push
```

## Data Architecture（唯一の定義）

- **Source of Truth（SoT）**
  - 建物 SoT: `data/tatemono_map.sqlite3` の `buildings`。
  - Canonical入力 SoT: `data/canonical/` 配下（例: `data/canonical/buildings_master.csv`）。
  - listings SoT: `data/tatemono_map.sqlite3` の `listings` のみ（`public.sqlite3` は SoT ではない）。
- **公開DBの役割**
  - `scripts/publish_public.ps1` は main DB から公開に必要な最小テーブルのみを `data/public/public.sqlite3` にコピーする。
  - 必須コピー: `buildings`, `building_summaries`。任意コピー: `building_key_aliases`（存在時のみ）。
  - `public.sqlite3` に `listings` は含めない（サイズ/プライバシー/公開性能のため）。UI は `building_summaries` を参照する。
- **フロントエンド実行時の参照元**
  - Runtime UI は GitHub Pages 上の `dist/` を読む。
  - `dist/` は Git 管理せず、Pages CI（`.github/workflows/deploy_pages.yml`）が毎回 `data/public/public.sqlite3` から再生成する。

```text
data/canonical/*
      -> data/tatemono_map.sqlite3 (main SoT: buildings/listings)
      -> data/public/public.sqlite3 (privacy-safe derived snapshot)
      -> dist/ (CI build artifact)
      -> GitHub Pages UI
```

## Deployment Model (Current)

- main branch tracks source code only.
- dist/ is a generated build artifact.
- dist/ is NOT committed to main.
- GitHub Pages is deployed via GitHub Actions.
- Local preview must be served over HTTP (file:// is not supported).

## 運用の唯一の正解（Windows / PowerShell 7）

> 週次運用の 1 コマンドは `scripts/run_all_latest.ps1` です（sync -> run_pdf_zip_latest -> 最新 master_import.csv 自動選択 -> run_to_pages -> 入居ラベル検証）。

### 1) 初回セットアップ（setup）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\setup.ps1" -RepoPath $REPO
```

- `scripts/setup.ps1` は冪等（idempotent）です。
- `.venv` と requirements フィンガープリント（ハッシュ）が前回と同じ場合、`pip install` / `pip install -e` をスキップします。

### 2) 初回 seed（buildings投入）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_to_pages.ps1" -RepoPath $REPO
```

- 手動確認済み CSV（`buildings_seed_ui.csv`）を canonical DB の `buildings` へ投入します。
- `canonical_name` / `canonical_address` は自動上書きしません。

### 3) 週次1コマンド（run_all_latest）

#### 入力 ZIP の置き場・命名規則（推奨）
- 置き場: `tmp/manual/inputs/pdf_zips/`
- 命名: `リアプロ-*.zip` / `ウラックス-*.zip`
- ZIP はローカル入力物として扱い、コミットしません（`.gitignore`）。

#### 推奨実行例（ZIP 置き場を repo 内に固定）
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$ZIP_DIR = Join-Path $REPO "tmp/manual/inputs/pdf_zips"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_all_latest.ps1" -RepoPath $REPO -DownloadsDir $ZIP_DIR -QcMode warn
```

#### push したくない場合
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$ZIP_DIR = Join-Path $REPO "tmp/manual/inputs/pdf_zips"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_all_latest.ps1" -RepoPath $REPO -DownloadsDir $ZIP_DIR -QcMode warn -SkipPush
```

#### 旧フローを手動で分けたい場合
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_to_pages.ps1" -RepoPath $REPO
```

- `run_all_latest` は `buildings` を再構築しません（空室取り込み + 建物突合 + 公開生成）。
- `ingest_master_import` 実行時に `buildings.norm_name` / `buildings.norm_address` は毎回自動再正規化されます（手作業不要）。

#### 再正規化のみ先に実行したい場合（任意）
```powershell
python -m tatemono_map.building_registry.renormalize_buildings --db .\data\tatemono_map.sqlite3
```

#### unmatched の簡易検証例（sqlite3）
```sql
select count(*) as unresolved_sources
from building_sources
where source = 'master_import' and (building_id is null or building_id='');
```

## 運用ポリシー（現状仕様）

- 現状の ingest は **`buildings` にマッチできた空室のみ `listings` に取り込み**、未マッチは `tmp/review/unmatched_listings_*.csv` に出力して取り込みません（今は捨てる運用）。
- 判断理由は **MVPローンチと収益化を優先**するためです。マッチ精度の追い込みは、運用しながら PDCA で段階改善します。

### 監視ポイント（毎週）

- ingest 実行ログの `attached_listings` / `unresolved` を記録し、`unresolved` の急増をアラート扱いにします。
- `tmp/review/unmatched_listings_*.csv` の `reason` を集計し、上位パターン（住所欠落・名称揺れ・ソース偏り）から改善対象を決めます。
- 既存建物へのマッチ改善（正規化・alias）と、将来の建物自動追加は別トラックで管理します。

### UI 指標の見方

- 公開 UI の「空部屋」は `data/public/public.sqlite3` の `building_summaries.vacancy_count` 合計を正とします。
- 確認クエリ: `select coalesce(sum(vacancy_count), 0) from building_summaries;`
- 将来改善（PR3）: [docs/roadmap_pr3_auto_add_buildings.md](docs/roadmap_pr3_auto_add_buildings.md)

### 4) 公開反映（GitHub Pages）

#### 一発実行（repo 指定・どこからでも実行可）

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_to_pages.ps1" -RepoPath $REPO
```

- 上記 1 行で、`master_import.csv` の自動検出 → main DB ingest → `publish_public.ps1` → `dist/data/buildings.v2.min.json` / `dist/data/buildings.json` 再生成 → 0件ガード → `git add/commit/push` まで完了します。
- CSV を明示したい場合は `-CsvPath <path-to-master_import.csv>`、コミット文言を固定したい場合は `-Message "..."` を追加します。
- `scripts/run_to_pages.ps1` は ingest と公開データ更新の運用コマンドです。Pages への公開物は Actions が `data/public/public.sqlite3` を入力に再生成します。

### フォルダ役割（固定）

- `data/canonical/`: Canonical入力（追跡対象）。
- `data/`: main DB（private運用。`data/tatemono_map.sqlite3`）。
- `data/public/`: 公開DB（追跡対象。`data/public/public.sqlite3`）。ローカル確認だけでは更新せず、更新時のみ明示的に `scripts/publish_public.ps1` / `scripts/run_to_pages.ps1` を実行します。
- `tmp/`: 一時作業・review出力のみ（scratch）。

#### “空部屋” の定義（UI 表示）

- UI の「空部屋」は **`data/public/public.sqlite3` の `building_summaries.vacancy_count` 合計** です。
- 入居可能日は `ulucks` の業務ルールを反映します。`availability_raw` が空欄の場合は「即入居」扱いとして正規化され、`building_summaries.building_availability_label` は `入居` になります。
- つまり確認式は次です。

```sql
select coalesce(sum(vacancy_count), 0) from building_summaries;
```

- `building_summaries` だけで建物名と入居可ラベルを確認する PowerShell 7 ワンライナー:

```powershell
python -c "import sqlite3; c=sqlite3.connect(r'data/public/public.sqlite3'); q='select name, coalesce(nullif(trim(building_availability_label), ?), ?) from building_summaries order by name limit 50'; [print(f'{n}\t{l}') for n, l in c.execute(q, ('', '—'))]"
```

- `listings count (main)`（`data/tatemono_map.sqlite3`）とは母集団・集計単位が異なるため、同値である必要はありません。
- `public.sqlite3` には `listings` テーブルは無く、公開用に必要なテーブルだけを持ちます。

## GitHub Pages 公開フロー

### 公開の仕組み
- GitHub Pages の Source は **GitHub Actions**（`main` push 起動）を使用します。
- 公開入力は `data/public/public.sqlite3` です（git 管理対象）。
- `dist/` は git 管理対象ではなく、CI（`.github/workflows/deploy_pages.yml`）が毎回 `data/public/public.sqlite3` から再生成して deploy します。

### トラブルシュート（反映されない時）
1. GitHub の **Actions** で `Deploy static site to GitHub Pages` が `Success` になっているか確認する。
2. `git log -- data/public/public.sqlite3` で最新コミットに DB 更新が含まれているか確認する。
3. `curl.exe -s https://aik38.github.io/tatemono-map/build_info.json` で Pages 配信中の build 情報を確認する。
4. スマホ/ブラウザで古く見える場合は、シークレットウィンドウで開くか、対象サイトのキャッシュ/サイトデータを削除して再読み込みする。

### よくあるミス
- `dist/` を push しても公開反映には使われない（CI が再生成する）。**正道は `data/public/public.sqlite3` を commit/push すること。**
- `main` 以外のブランチに push している。
- `data/public/public.sqlite3` の更新を commit していない。
- ingest または `publish_public` が失敗して DB が更新されていない。

## Canonical DB 運用ルール

- Canonical buildings CSV は `data/canonical/buildings_master.csv` です。
- `tmp/` 配下は一時作業用（レビュー・中間成果物）であり Canonical ではありません。
- Web 表示の建物名/住所と KPI（建物数・空室数）は Canonical buildings を基準に計算されます。

### Canonical 更新の最短 Runbook

1. `data/canonical/buildings_master.csv` を更新する。
2. Canonical を DB へ投入する。
   - `python -m tatemono_map.cli.master_import --db data/tatemono_map.sqlite3`
3. 公開DBを更新する。
   - `pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\publish_public.ps1 -RepoPath .`
4. （ローカル確認する場合のみ）public DB から `dist/` を生成する。
   - `python -m tatemono_map.render.build --db-path data/public/public.sqlite3 --output-dir dist --version all`

### KPI 検証クエリ（sqlite3）

```sql
select count(*) from buildings;
select coalesce(sum(s.vacancy_count), 0)
from building_summaries s
join buildings b on b.building_id = s.building_key;
```


## Move-in availability 検証 Runbook（PowerShell 単発）

```powershell
$ErrorActionPreference = "Stop"
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$DB = Join-Path $REPO "data/public/public.sqlite3"
$BASE = "https://aik38.github.io/tatemono-map"

pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO/sync.ps1" -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO/scripts/run_all_latest.ps1" -RepoPath $REPO
$csv = Get-ChildItem -Path "$REPO/tmp/pdf_pipeline/out" -Filter "master_import.csv" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
python -m tatemono_map.cli.diagnose_availability --csv $csv --db $DB
Invoke-WebRequest -UseBasicParsing "$BASE/data/buildings.v2.min.json" | Out-Null
```

## トラブルシュート（availability / SQL）

- `Advanced encoding /90msp-RKSJ-H not implemented yet` は PDF 由来テキストで一部エンコーディングを復元できない時の既知警告です。`master_import.csv` の該当行で文字化けがなければ通常は継続して問題ありません。文字化けがある場合は OCR/抽出条件の見直し、または対象 PDF を再取得して再実行してください。
- SQL で建物名を参照する時は `building_summaries.name` を使ってください。`building_name` 列は `building_summaries` にはありません。
- `buildings` テーブルは `building_key` 列を持たないため、`building_summaries` と直接 `building_key` で join しません。join する場合は `buildings.building_id = building_summaries.building_key` を使用してください。

## テスト（推奨）

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q tests
```

## ローカル確認（唯一の正解 / Pages-like）

- 実行コマンド（dist 生成 + ガード + Pages-like 配信）:

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev_dist.ps1" -RepoPath $REPO -Port 8788
```

- `$REPO` を明示して実行すると、どの作業ディレクトリからでも迷わず同じ手順で起動できます。
- `scripts/dev_dist.ps1` は `data/public/public.sqlite3` を再生成しません（`git status` を不要に汚さないため）。公開DBを更新したいときだけ `scripts/publish_public.ps1` または `scripts/run_to_pages.ps1` を使ってください。
- ローカルプレビューは **HTTP 配信のみ対応** です。**`file://` は禁止**（GitHub Pages と挙動が一致しません）。

- 確認 URL（必ずこの形）:

```text
http://127.0.0.1:8788/tatemono-map/
```

- **`file://` で `dist/index.html` を直接開くのは禁止**です。`fetch` / 相対パス / ルーティング検証が壊れて、GitHub Pages との挙動差分が出ます。
- `scripts/dev_dist.ps1` は `/tatemono-map/` プレフィックスで配信するため、Pages と同じパス条件で確認できます。



### ローカルHTTP確認の簡易ドクター（Model B）

```powershell
# 1) プレビュー起動（唯一の正解）
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev_dist.ps1" -RepoPath $REPO -Port 8788

# 2) 別ターミナルで状態確認（通常は clean のまま）
git -C $REPO status -sb
# 想定: 変更なし、または公開DB更新を明示実行した場合のみ data/public/public.sqlite3 の差分

# 3) エントリポイント確認
# http://127.0.0.1:8788/tatemono-map/
```

### Pagesとローカルの一致確認

```powershell
# local
Get-Content -Raw .\dist\build_info.json | ConvertFrom-Json

# pages
curl.exe -fsSL https://aik38.github.io/tatemono-map/build_info.json

# compare (git_sha 優先。無ければ buildings_count / vacancy_total)
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_pages_parity.ps1
```

- 比較時は `git_sha` があれば最優先で一致確認し、無い場合は `buildings_count` と `vacancy_total` を比較します。

## What / Why
このリポジトリは、Google Maps / Street View（ストリートビュー）と連携可能な「不動産データベース母艦」を作るための基盤です。  
北九州は**パイロット地域**であり、固定ターゲットではありません。  
MVP は賃貸空室データの整備を中心に進めますが、将来的には売却査定や解体比較のリード獲得にも拡張します。  
正本（Canonical Source of Truth）は SQLite の `buildings` テーブルです。

## Non-goals（このPRDでやらないこと）
- UI テンプレートや見た目の最適化を先行しない。
- `buildings` の canonical 項目を自動更新しない。
- 旧来の「マスター再構築」フローを現行運用に戻さない。

## Docs
- ドキュメント入口: [docs/README.md](docs/README.md)
- 方針（唯一の運用方針）: [PLAN.md](PLAN.md)
- 仕様（役割分担・禁止事項・更新方針）: [docs/spec.md](docs/spec.md)
- 運用手順: [docs/runbook.md](docs/runbook.md)
- 工程管理（Phase/DoD）: [docs/wbs.md](docs/wbs.md)


### 4) 建物詳細に表示される情報（v2 UI）
- 建物詳細ページは `building_summaries` から以下を表示します。
  - 空室数 / 家賃レンジ / 面積レンジ / 間取りタイプ / 入居可能日
  - **築年数（age_years） / 構造（structure）**
- `age_years` / `structure` が `master_import.csv` に無い、または欠損している場合は `—` 表示になります。

### 検証チェックリスト（minimal commands）
```powershell
python -m pytest -q tests/test_building_registry.py tests/test_building_summaries.py tests/test_schema_migration.py tests/test_render_dist.py
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 -RepoPath . -DbPath .\data\tatemono_map.sqlite3 -MasterImportCsv <outdir>\master_import.csv
python -m tatemono_map.render.build --db-path data/public/public.sqlite3 --output-dir dist --version v2
```
- `data/public/public.sqlite3` の `building_summaries` に `age_years` / `structure` 列があることを確認します。
- `dist/b/*.html` の建物詳細で「築年数」「構造」が表示され、「最終更新日時」が表示されないことを確認します。


### v2 JSON 配信ヘッダー確認（gzip / br）
- Pages 上で `buildings.v2.min.json` / `buildings.json` の圧縮配信を確認する手順です（実装変更は不要）。

```powershell
curl.exe -I https://aik38.github.io/tatemono-map/data/buildings.v2.min.json
Invoke-WebRequest -Method Head https://aik38.github.io/tatemono-map/data/buildings.v2.min.json | Select-Object -ExpandProperty Headers
```

- `Content-Encoding: gzip` または `Content-Encoding: br` を確認します。
- 併せて Chrome DevTools > Network で同ファイルを開き、Response Headers の `Content-Encoding` を確認します。


### Pagesズレ防止の運用コマンド（JSON再生成 + 0件ガード込み）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_to_pages.ps1" -RepoPath $REPO
```

- `run_to_pages.ps1` は `data/public/public.sqlite3` 生成後に必ず以下を更新します。
  - `dist/data/buildings.v2.min.json`
  - `dist/data/buildings.json`
- `dist/data/buildings.v2.min.json` の件数が `0` の場合は `throw` して終了し、壊れた成果物を push しません。
- ローカル検証は `file://` 直開きではなく、`scripts/dev_dist.ps1` による HTTP 配信のみを使用してください。

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev_dist.ps1" -RepoPath $REPO -Port 8788
```

- ローカル確認 URL 例: `http://127.0.0.1:8788/tatemono-map/`（ポートは任意）

## 小倉北区MVP: ルート別データフロー（Ulucks/RealPro + Mansion-review + Orient）

### 監査結果（Inventory / Audit）
- A) Ulucks/RealPro（listings）
  - 抽出: `master_import.csv` の `age_years / structure / availability_raw / built_*` を取り込み。
  - 格納: `listings`（空室単位）に保持し、`building_summaries` を再集約。
  - UI: `building_summaries` を公開DBへコピーし `dist` の建物JSONへ反映。
- B) Mansion-review（賃貸/分譲）
  - 既存の HTML/クロールCSV化スクリプトは建物名・住所中心で、`structure / age_years / availability` の canonical 格納経路が未整備。
  - 対応: `python -m tatemono_map.cli.import_building_master` で `buildings` に建物属性を保存し、空室0でも集約反映。
- C) Orient 建物一覧
  - 既存ルート定義が薄く、Aのような listings 経路はなし（建物マスター系として扱うのが自然）。
  - 対応: Mansion-review と同じ `import_building_master` で `buildings` へ投入。

### 正規化規約（Canonical contract）
- `buildings` 側に建物属性を保持:
  - `structure` (TEXT)
  - `age_years` (INTEGER)
  - `built_year` (INTEGER)
  - `availability_raw` / `availability_label` (TEXT, NULL許容)
- `availability_label` は listings 由来を原則優先。建物マスターのみのルートでは NULL のまま保持（勝手に「即入居」にしない）。

### 集約ルール（building_summaries）
- `structure`, `age_years`, `built_year/age` は listings 優先、欠損時に buildings フォールバック。
- `building_availability_label` は listings がある場合のみ計算。空室0建物では NULL のまま。

### 運用コマンド（例）
```powershell
# Mansion-review / Orient 建物マスター取り込み
python -m tatemono_map.cli.import_building_master --db data/tatemono_map.sqlite3 --csv tmp/manual/outputs/mansion_review/<file>.csv --source mansion_review
python -m tatemono_map.cli.import_building_master --db data/tatemono_map.sqlite3 --csv tmp/manual/outputs/orient/<file>.csv --source orient

# 集約再生成 + QC
python -m tatemono_map.normalize.building_summaries --db-path data/tatemono_map.sqlite3
python -m tatemono_map.cli.diagnose_availability --csv tmp/manual/inputs/master_import.csv --db data/tatemono_map.sqlite3
```

`diagnose_availability` は以下の指標を出力します:
- `zero_vacancy_buildings`
- `zero_vacancy_structure_filled`（埋まり率%）
- `zero_vacancy_age_filled`（埋まり率%）
