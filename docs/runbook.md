# runbook（運用手順）

現行運用は **初回 seed + 週次 1 コマンド更新** です。  
旧来のマスター再構築フローは **現行運用では使用しません**。

## 0. 事前準備（Prerequisites / 前提条件）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -RepoPath .
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -RepoPath .
```

## 1. 初回 seed（初回のみ / 再実行可）
手動確認済み CSV を canonical DB（`buildings`）へ投入します。

### 入力ファイル
- `tmp/manual/inputs/buildings_seed_ui.csv`

### 実行コマンド
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 `
  -DbPath .\data\tatemono_map.sqlite3 `
  -CsvPath .\tmp\manual\inputs\buildings_seed_ui.csv
```

### 期待される挙動
- 既存建物を再利用し、重複追加を避ける（idempotent / 冪等）。
- `canonical_name` / `canonical_address` は自動上書きしない。

## 2. 週次運用（1 command）

### 入力 ZIP の置き場（推奨）
- `tmp/manual/inputs/pdf_zips/` に配置する。
- ファイル名は `リアプロ-*.zip` / `ウラックス-*.zip`。
- ZIP はローカル入力物として扱い、コミットしない（`.gitignore`）。

### 実行コマンド（推奨）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 -RepoPath . -DbPath .\data\tatemono_map.sqlite3 -DownloadsDir .\tmp\manual\inputs\pdf_zips -QcMode warn
```

### ZIP 処理を飛ばす場合（`master_import.csv` を直接指定）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 -RepoPath . -DbPath .\data\tatemono_map.sqlite3 -MasterImportCsv <outdir>\master_import.csv
```

### 実行内容
1. PDF バッチ処理（listing 抽出）
2. `master_import.csv` ingest（listings 更新 + 建物突合）
3. review CSV 出力（`tmp/review/`）
4. `publish_public` 実行（`public.sqlite3` 更新）
5. `render.build` 実行（`dist/` 更新。`data/public/public.sqlite3` を入力に使うため、Pages の生成結果と合わせやすい）

> 注: 週次運用は `buildings` テーブルを再構築しません。既存 canonical を維持しつつ、新規建物のみ追加します。
## 3. review CSV の意味（トリアージ）
`tmp/review/` に以下が出力されます。

- `new_buildings_*.csv`
  - 自動で新規追加した建物の確認用。誤追加がないか点検し、必要に応じて alias/seed で統合。
- `suspects_*.csv`
  - 候補はあるが確信不足（僅差・競合・閾値不足）。人手判断で統合先を決める。
- `unmatched_listings_*.csv`
  - building_id が確定できなかった listing。住所揺れ・建物名揺れ・入力欠損の切り分け対象。

### 推奨トリアージ順
1. `suspects` を先に確認（既存建物へ寄せられる可能性が高い）。
2. `unmatched` を確認し、正規化ルール追加または seed/alias 反映を判断。
3. `new_buildings` を最後に確認し、不要な新規分裂がないか確認。

## 4. canonical 保護ポリシー
- canonical 値は自動で書き換えない。
- 修正が必要な場合は、手動確認後に seed CSV や alias/evidence 管理で反映する。
- 不一致が残っても weekly パイプラインは継続し、review CSV で後追い対応する。

## 5. 公開（GitHub Pages）反映時のコミット方針
- コミット対象は原則 `data/public/public.sqlite3` のみ。
- `dist/` はローカルプレビュー用であり、GitHub Pages 本番では CI が `data/public/public.sqlite3` から再生成してデプロイする。

`git add data/public/public.sqlite3` で ignored と表示される場合は、先に ignore ルールを確認する。

```powershell
git check-ignore -v data/public/public.sqlite3
```

- 追跡済みなら通常 commit できる。
- 未追跡で追加できない場合のみ `git add -f data/public/public.sqlite3` を最終手段として使う（通常は不要）。

## 6. トラブルシュート
- `publish_public` がロックで失敗する:
  1. DB Browser for SQLite を閉じる。
  2. VSCode の SQLite 拡張で `public.sqlite3` を開いているタブを閉じる。
  3. Explorer のプレビュー（詳細ウィンドウ含む）を閉じる。
  4. 数秒待ってから `scripts/publish_public.ps1` を再実行する。
- `weekly_update` が `rows=0` で停止する:
  - 安全停止（新しい入力なし）。`tmp/manual/inputs/pdf_zips/` の ZIP 配置と `リアプロ-*.zip` / `ウラックス-*.zip` のファイル名を確認する。
- `weekly_update` が `master_import` header mismatch で停止する:
  - `tmp/pdf_pipeline/out/<timestamp>/master_import.csv` のヘッダを確認する。`run_pdf_zip` 側で `master_import.csv` 生成が壊れている可能性がある。

## 7. 安全性チェック（idempotency checklist）
- seed を 2 回実行しても `buildings` 件数が不自然に増えない。
- weekly を連続実行しても canonical が勝手に変わらない。
- unmatched がある場合は `tmp/review/unmatched_listings_*.csv` が生成される。
