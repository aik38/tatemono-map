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
- review CSV は `tmp/review/` に出力されます（`suspects` / `unmatched_listings` / `new_buildings`）。
- 推奨トリアージ順は `suspects` → `unmatched_listings` → `new_buildings` です。

### 4) 公開反映（GitHub Pages）

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\publish_public.ps1 -RepoPath .
```

- GitHub Pages への反映で push すべきものは、原則 `data/public/public.sqlite3`（必要なら周辺メタ）です。
- `weekly_update` 実行後は、更新された `data/public/public.sqlite3` を commit/push します。
- `dist/` は `.gitignore` 対象のビルド成果物であり、Pages は CI（`.github/workflows/pages.yml`）が `data/public/public.sqlite3` から生成してデプロイします。

`git add data/public/public.sqlite3` で ignored と出る場合は、先に以下で確認します。

```powershell
git check-ignore -v data/public/public.sqlite3
```

- 何も出力されなければ、`data/public/public.sqlite3` は ignore されていません。
- 追跡済みなら通常どおり commit できます。
- 未追跡でどうしても追加できない場合のみ、最終手段として `git add -f data/public/public.sqlite3` を使います（通常は不要）。


## Canonical DB 運用ルール

## GitHub Pages 公開フロー

### 公開の仕組み
- GitHub Pages の Source は **GitHub Actions** を使用します（`main` への push で実行）。
- 公開入力は `data/public/public.sqlite3` です（git 管理対象として追跡します）。
- `dist/` は git 管理対象ではなく、push しても公開には使われません。
- push 後、`.github/workflows/pages.yml` が `data/public/public.sqlite3` から `dist/` を再生成します。
- 生成物は artifact `github-pages` として upload され、deploy されると公開 URL に反映されます。

### 確認手順
1. GitHub の **Actions** で `Deploy static site to GitHub Pages` が `Success` になっていることを確認する。
2. 対象 run の Artifacts から `github-pages` をダウンロードし、`dist/` の内容を確認する。
3. `public.sqlite3` の `building_summaries` 件数を SQL で確認する。
   ```sql
   select count(*) from building_summaries;
   ```
4. Web が古く見える場合は、シークレットウィンドウまたはハードリロードでキャッシュを切り分ける。

### よくあるミス
- `dist/` を push しても意味がない（CI が毎回再生成する）。
- `main` 以外のブランチに push している。
- `data/public/public.sqlite3` が更新されていない。
- `weekly_update` が失敗しており、DB が実際には更新されていない。

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
