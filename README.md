# tatemono-map

## 開発同期（GitHub↔ローカル）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\sync.ps1" -RepoPath $REPO
git -C $REPO status -sb
git -C $REPO push
```

## 運用の唯一の正解（Windows / PowerShell 7）

### 1) 初回セットアップ（setup）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\setup.ps1" -RepoPath $REPO
```

- `scripts/setup.ps1` は冪等（idempotent）です。
- `.venv` と requirements フィンガープリント（ハッシュ）が前回と同じ場合、`pip install` / `pip install -e` をスキップします。

### 2) 初回 seed（buildings投入）

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 `
  -DbPath .\data\tatemono_map.sqlite3 `
  -CsvPath .\tmp\manual\inputs\buildings_seed_ui.csv
```

- 手動確認済み CSV（`buildings_seed_ui.csv`）を canonical DB の `buildings` へ投入します。
- `canonical_name` / `canonical_address` は自動上書きしません。

### 3) 週次1コマンド（weekly_update）

#### 入力 ZIP の置き場・命名規則（推奨）
- 置き場: `tmp/manual/inputs/pdf_zips/`
- 命名: `リアプロ-*.zip` / `ウラックス-*.zip`
- ZIP はローカル入力物として扱い、コミットしません（`.gitignore`）。

#### 推奨実行例
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 -RepoPath . -DbPath .\data\tatemono_map.sqlite3 -DownloadsDir .\tmp\manual\inputs\pdf_zips -QcMode warn
```

#### ZIP処理をスキップして `master_import.csv` を直指定
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 -RepoPath . -DbPath .\data\tatemono_map.sqlite3 -MasterImportCsv <outdir>\master_import.csv
```

- `weekly_update` は `buildings` を再構築しません（空室取り込み + 建物突合 + review CSV + 公開生成）。
- `ingest_master_import` 実行時に `buildings.norm_name` / `buildings.norm_address` は毎回自動再正規化されます（手作業不要）。
- review CSV は `tmp/review/` に出力されます（`suspects` / `unmatched_listings` / `new_buildings`）。
- 推奨トリアージ順は `suspects` → `unmatched_listings` → `new_buildings` です。

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

### 4) 公開反映（GitHub Pages）

#### 一発実行（repo 指定・どこからでも実行可）

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_to_pages.ps1" -RepoPath $REPO
```

- 上記 1 行で、`master_import.csv` の自動検出 → main DB ingest → `publish_public.ps1` → `git add/commit/push` まで完了します。
- CSV を明示したい場合は `-CsvPath <path-to-master_import.csv>`、コミット文言を固定したい場合は `-Message "..."` を追加します。
- `scripts/run_to_pages.ps1` は `data/public/public.sqlite3` だけを stage します（`git add -f` は不要）。

#### “空部屋” の定義（UI 表示）

- UI の「空部屋」は **`data/public/public.sqlite3` の `building_summaries.vacancy_count` 合計** です。
- つまり確認式は次です。

```sql
select coalesce(sum(vacancy_count), 0) from building_summaries;
```

- `listings count (main)`（`data/tatemono_map.sqlite3`）とは母集団・集計単位が異なるため、同値である必要はありません。
- `public.sqlite3` には `listings` テーブルは無く、公開用に必要なテーブルだけを持ちます。

## GitHub Pages 公開フロー

### 公開の仕組み
- GitHub Pages の Source は **GitHub Actions**（`main` push 起動）を使用します。
- 公開入力は `data/public/public.sqlite3` です（git 管理対象）。
- `dist/` は git 管理対象ではなく、CI（`.github/workflows/pages.yml`）が毎回 `data/public/public.sqlite3` から再生成して deploy します。

### トラブルシュート（反映されない時）
1. GitHub の **Actions** で `Deploy static site to GitHub Pages` が `Success` になっているか確認する。
2. `git log -- data/public/public.sqlite3` で最新コミットに DB 更新が含まれているか確認する。
3. スマホ/ブラウザで古く見える場合は、シークレットウィンドウで開くか、対象サイトのキャッシュ/サイトデータを削除して再読み込みする。

### よくあるミス
- `dist/` を push しても公開反映には使われない（CI が再生成する）。
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
3. 公開物を再生成する。
   - `python -m tatemono_map.render.build --db-path data/tatemono_map.sqlite3 --output-dir dist --version all`

### KPI 検証クエリ（sqlite3）

```sql
select count(*) from buildings;
select coalesce(sum(s.vacancy_count), 0)
from building_summaries s
join buildings b on b.building_id = s.building_key;
```

## テスト（推奨）

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest -q tests
```

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
