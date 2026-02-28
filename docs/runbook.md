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
python -m tatemono_map.render.build --db-path data/public/public.sqlite3 --output-dir dist --version v2
python -m http.server 8000 -d dist
```

2) push 後の Pages 応答確認

```powershell
Invoke-WebRequest https://aik38.github.io/tatemono-map/index.html | Select-Object StatusCode,Headers
```

- `Headers.Last-Modified` / `Headers.ETag` が更新されていることを確認する。
- ブラウザ確認はシークレットウィンドウで行い、必要に応じて `Ctrl+F5`。

---

## トラブルシュート

1. Actions の `Deploy GitHub Pages` が Success か確認。
2. `git status` で `data/public/public.sqlite3` が commit 済みか確認。
3. `dist/` を commit していないことを確認。
4. `https://aik38.github.io/tatemono-map/data/public/public.sqlite3` が 404 でも正常（Pages は `dist/` のみ配信）。
5. プレビューで Not Found が出る場合は、環境ルーティング由来のことがあるため上記「2段確認」を優先する。
