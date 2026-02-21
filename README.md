# tatemono-map

Kitakyushu（北九州）向け賃貸データの **建物単位 canonical DB + 静的サイト公開** システムです。

## 1) What / Why
- 目的は、複数ソース（Ulucks / RealPro など）の空室情報を毎週取り込み、建物単位で整合した公開データを安定配信することです。
- システムの正本は SQLite の `buildings` テーブルです。
- 週次運用は「空室更新 + 新規建物のみ追加」を行い、既存 canonical 情報は保護します。

詳細ドキュメントは [docs/README.md](docs/README.md) を参照してください。

## 2) Non-goals
- `buildings_master` を週次で再構築する運用は行いません。
- `canonical_name` / `canonical_address` の自動上書きは行いません。

## 3) Data model overview
- `buildings`（canonical）
  - 建物正本。`canonical_*` は手動判断を前提に保護。
- `listings`（derived）
  - 各ソースの募集情報を正規化・突合して保持。
- 公開成果物
  - `data/public/public.sqlite3`（公開DB）
  - `dist/`（GitHub Pages 向け静的HTML）
- レビュー成果物
  - `tmp/review/*.csv`（要確認データ）

## 4) I/O flow

```text
Sources (Ulucks / RealPro / etc)
  -> normalize
  -> ingest listings
  -> match to buildings
  -> publish_public
  -> render.build
  -> data/public/public.sqlite3 + dist/

Seed CSV (manual UI corrections)
  -> seed_from_ui
  -> buildings (canonical, no auto-overwrite)
```

## 5) Commands (PowerShell)

### Setup / sync
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -RepoPath .
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -RepoPath .
```

### Initial seed（idempotent）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 `
  -DbPath .\data\tatemono_map.sqlite3 `
  -CsvPath .\tmp\manual\inputs\buildings_seed_ui.csv
```

### Weekly update（1 command）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\weekly_update.ps1 `
  -RepoPath . `
  -DbPath .\data\tatemono_map.sqlite3
```

### Output locations
- `tmp/review/` : `new_buildings_*.csv`, `suspects_*.csv`, `unmatched_listings_*.csv`
- `data/public/public.sqlite3` : 公開DB
- `dist/` : 静的HTML

## 6) Safety rules
- `canonical_name` / `canonical_address` は自動上書きしません。
- `seed_buildings_from_ui.ps1` と `weekly_update.ps1` は再実行しても安全（idempotent）な運用を前提にしています。
- 未解決マッチは `tmp/review/*.csv` に出力し、パイプラインは継続します。

## 7) Quick sanity checks（copy/paste）

### A. seed を 2 回実行して建物件数が増えないこと
```powershell
python - <<'PY'
import sqlite3
con = sqlite3.connect('data/tatemono_map.sqlite3')
print(con.execute('select count(*) from buildings').fetchone()[0])
con.close()
PY

pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 -DbPath .\data\tatemono_map.sqlite3 -CsvPath .\tmp\manual\inputs\buildings_seed_ui.csv
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed_buildings_from_ui.ps1 -DbPath .\data\tatemono_map.sqlite3 -CsvPath .\tmp\manual\inputs\buildings_seed_ui.csv

python - <<'PY'
import sqlite3
con = sqlite3.connect('data/tatemono_map.sqlite3')
print(con.execute('select count(*) from buildings').fetchone()[0])
con.close()
PY
```

### B. canonical が自動変更されないこと（スナップショット比較）
```powershell
python - <<'PY'
import sqlite3, hashlib
con = sqlite3.connect('data/tatemono_map.sqlite3')
rows = con.execute('select id, canonical_name, canonical_address from buildings order by id').fetchall()
blob = '\n'.join(f"{r[0]}|{r[1] or ''}|{r[2] or ''}" for r in rows).encode('utf-8')
print(hashlib.sha256(blob).hexdigest())
con.close()
PY
```

### C. review CSV の生成確認
```powershell
Get-ChildItem .\tmp\review\*.csv | Sort-Object LastWriteTime -Desc | Select-Object -First 10
```

---

## Key docs
- [docs/README.md](docs/README.md)（ドキュメント索引）
- [docs/spec.md](docs/spec.md)（システム仕様）
- [docs/runbook.md](docs/runbook.md)（初回投入と週次運用）
- [docs/data_contract.md](docs/data_contract.md)（主な入出力契約）
