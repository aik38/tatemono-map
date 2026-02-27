# runbook（運用手順）

現行運用の公開反映は **週次 1 コマンド** が正です。  
旧来の「dist を手動 push」運用は使用しません。

## 0) データ役割（先にここだけ固定）

- main DB（SoT）: `data/tatemono_map.sqlite3`
- public DB（派生スナップショット）: `data/public/public.sqlite3`
- Pages 本番 UI: CI が public DB から再生成した `dist/`
- `public.sqlite3` は `buildings` / `building_summaries`（+存在時 `building_key_aliases`）のみを持ち、`listings` は持たない

## 1) 週次 1 コマンド（唯一の運用）

```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_to_pages.ps1" -RepoPath $REPO
```

`scripts/run_to_pages.ps1` の実行内容（ワンショット）:
1. `master_import.csv` を検出して ingest（main DB 更新）
2. `scripts/publish_public.ps1` 実行（public DB 更新）
3. `git add data/public/public.sqlite3` -> commit -> push

## 2) KPI チェック（毎週）

### A. ingest 側 KPI（ログ）
- `attached_listings`
- `unresolved`

> `unresolved` の急増は要調査。`tmp/review/unmatched_listings_*.csv` を確認する。

### B. public 側 KPI（公開値）

```sql
select coalesce(sum(vacancy_count), 0) as public_vacancy
from building_summaries;
```

- 実行先: `data/public/public.sqlite3`
- UI の「空部屋」はこの値を基準に確認する。

## 3) トラブルシュート・チェックリスト

1. **Actions status**
   - GitHub Actions `Deploy static site to GitHub Pages` が `Success` か確認。
2. **cache**
   - 反映が古い場合、シークレットウィンドウ or サイトデータ削除で再読込。
3. **gitignore / commit 漏れ**
   - `git status` で `data/public/public.sqlite3` の更新が commit 済みか確認。
   - `dist/` は ignore 対象。push しても公開入力にはならない。
4. **DB lock（Windows）**
   - `publish_public.ps1` が lock で失敗したら、DB Browser / VSCode SQLite 拡張 / Explorer プレビューを閉じて再実行。

## 4) 補助コマンド（確認用）

```powershell
sqlite3 data/tatemono_map.sqlite3 "select count(*) from listings;"
sqlite3 data/public/public.sqlite3 "select count(*) from building_summaries;"
sqlite3 data/public/public.sqlite3 "select coalesce(sum(vacancy_count),0) from building_summaries;"
Get-Item data/public/public.sqlite3 | Format-List Length,LastWriteTime
```
