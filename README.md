# Tatemono Map（建物/不動産データAPI MVP）

**目的**：建物/不動産データを扱うAPI MVP「tatemono-map」を、**Windows 11 + PowerShell 7.x** だけでローカル起動・運用できるようにするための手順書です。

---

## 正本（PowerShell 一発手順）
以下を正本手順とします。`data/tatemono_map.sqlite3` を唯一のSQLite DBとして利用します。

```powershell
$env:SQLITE_DB_PATH = "data/tatemono_map.sqlite3"
python -m tatemono_map.cli.ulucks_run --url '<smartlink>' --db $env:SQLITE_DB_PATH --output dist
```

- 内部で `ingest -> parse -> normalize -> build -> audit` を順次実行します。
- 監査だけ実行したい場合は以下を使います。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/ps/doctor.ps1 -DbPath $env:SQLITE_DB_PATH
```

## Quick Start（Windows / PowerShell）
> This project intentionally does NOT use detail pages (smartview).

この章を **正本** とし、次の3手順を標準運用とします。いずれも実体パスは **`$env:USERPROFILE\tatemono-map` 固定** です。

- 前提: リポジトリ配置は **`$env:USERPROFILE\tatemono-map` に固定**
- OneDrive 配下の同名 repo は混在事故の原因になるため使用しない
- Smartlink URL 例は PowerShell で壊れないよう **単一引用符** を使う（`mail=` の `@` は `%40` で指定）

### A) build-only（既存DB → dist生成 → index.htmlを開く）
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Set-Location $REPO
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) { throw ".venv がありません。scripts/dev_setup.ps1 などで初期化してください。" }
. .\.venv\Scripts\Activate.ps1
if (-not $env:SQLITE_DB_PATH) { $env:SQLITE_DB_PATH = "data\tatemono_map.sqlite3" }
python -m tatemono_map.render.build --output-dir dist
Start-Process (Join-Path $REPO "dist\index.html")
```

### B) ingest（smartlink → DB更新 → normalize → dist生成 → open）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\run_ulucks_smartlink.ps1" -Url 'https://ulucks.example/smartlink/?link_id=YOUR_LINK_ID&mail=user%40example.com' -NoServe
```

### C) Manual PDF（正式ルートC: PDF→CSV→DB→dist）
PowerShell スクリプト運用の正本（推奨）は次です。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ulucks_manual_pdf.ps1 -CsvPath tmp/manual/ulucks_pdf_raw.csv -NoServe -Open
```

- `--no-serve:False` のような誤引数を避けるため、`-NoServe` 指定時だけ `--no-serve` を付ける実装です。
- 任意指定: `-DbPath`, `-OutputDir`, `-RepoPath`, `-Open`。

補足（誤解防止）:
- 「60件」は管理画面プルダウンの**表示件数の例**です。PDF件数そのものは管理会社・検索条件で変動し、10〜500件以上になることがあります。
- 物件別PDFはCSV化しやすく有利ですが、1 PDF が長すぎるとCSV化事故が増えるため、目安として **200〜300件程度で分割**（エリア/条件ごとに複数PDF）を推奨します。
- CLI は `--csv` で任意パスを受け付けるため、CSVファイル名は何でも構いません。
- ただし運用上は投入用の固定パス `tmp/manual/ulucks_pdf_raw.csv` を推奨します（上書き運用）。履歴を残す場合は `ulucks_pdf_raw_YYYYMMDD.csv` を保存し、投入前に `ulucks_pdf_raw.csv` へコピーしてください。

運用コマンド例（1ブロック）:

```powershell
# 任意CSVを指定（-CsvPath）して投入し、HTTPサーバは起動せず（-NoServe）、生成した index.html を開く（-Open）
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_ulucks_manual_pdf.ps1 -CsvPath tmp/manual/ulucks_pdf_raw_20260211.csv -NoServe -Open
```

取り込み CLI を直接実行する場合（Quickstart / サーバ起動なし）は次を正本にします。

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Set-Location $REPO
. .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m tatemono_map.cli.ulucks_manual_run --csv tmp/manual/ulucks_pdf_raw.csv --db data/tatemono_map.sqlite3 --output dist --no-serve
Start-Process dist/index.html
```

- CSV保存先は CLI の `--csv` で任意指定可（運用推奨は `tmp/manual/ulucks_pdf_raw.csv`）。
- DBは **`data/tatemono_map.sqlite3` 固定**（スクリプト実行時は `-DbPath` で上書き可）。

### C-2) 本番（GitHub Pages）更新手順（manual CSV）
`main` ブランチに `tmp/manual/ulucks_pdf_raw.csv` を push すると、GitHub Actions（`Deploy static site to GitHub Pages`）が次を自動実行します。

- **責務分離**:
  - Pages workflow は公開用の build/deploy（CSV → public DB 再生成 → dist 生成 → sanity check → deploy）のみを担当します。
  - テスト（`pytest`）は `ci` workflow 側で実行します。

1. `tmp/manual/ulucks_pdf_raw.csv` から `data/public/public.sqlite3` を再生成
2. その公開DBから `dist/` を再ビルド
3. GitHub Pages へデプロイ

運用フロー（人手）は次の4ステップです。

```powershell
# 1) CSVを差し替え
#    tmp/manual/ulucks_pdf_raw.csv

# 2) commit/push
git add tmp/manual/ulucks_pdf_raw.csv
git commit -m "Update manual ulucks CSV"
git push origin main

# 3) GitHub Actions の "Deploy static site to GitHub Pages" 完了を待つ
# 4) Repository > Environments > github-pages で Last deployed 更新を確認
```

### D) PDF batch pipeline（Quickstart）
- 本パイプラインは **Ulucks + Realpro の空室一覧専用**（Orientは対象外）です。

#### 1) 前提
- OS/シェル: **Windows 11 + PowerShell 7.5.x**
- repo の実体パス: **`%USERPROFILE%\tatemono-map` 固定**
- Python は必ず **`<repo>\.venv\Scripts\python.exe` のフルパス**を使います。
  - `./.venv/...` は「repo 直下にいる時だけ」正しいため、運用手順では使いません。

#### 2) 入力ファイル（ユーザー操作）
- `Downloads` に以下2種類の ZIP を置きます（複数ある場合は最新を自動採用）。
  - `リアプロ-*.zip`
  - `ウラックス-*.zip`

#### 3) 出力先（固定）
- 作業用（展開/集約）: `tmp\pdf_pipeline\work\<timestamp>`
  - `extract_realpro`, `extract_ulucks`
  - `realpro_pdfs`, `ulucks_pdfs`（PDF集約先）
- 成果物: `tmp\pdf_pipeline\out\<timestamp>`
  - `final.csv`
  - `stats.csv`
  - `todo_realpro_missing_address.csv`（後述QCで作成）

#### 4) PowerShell “一発”コマンド（コピペ実行）
以下をそのまま実行してください（PowerShell 7 互換）。

```powershell
$ErrorActionPreference="Stop"
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Set-Location $REPO
$PY = Join-Path $REPO ".venv\Scripts\python.exe"
$DL = Join-Path $env:USERPROFILE "Downloads"
$ZIPR = Get-ChildItem $DL -File | ? Name -like "リアプロ-*.zip"   | Sort LastWriteTime -Desc | Select -First 1
$ZIPU = Get-ChildItem $DL -File | ? Name -like "ウラックス-*.zip" | Sort LastWriteTime -Desc | Select -First 1
if(!$ZIPR){throw "Downloads に リアプロ-*.zip が見つかりません"}
if(!$ZIPU){throw "Downloads に ウラックス-*.zip が見つかりません"}
$TS=(Get-Date).ToString("yyyyMMdd_HHmmss")
$WORK=Join-Path $REPO "tmp\pdf_pipeline\work\$TS"
$OUT =Join-Path $REPO "tmp\pdf_pipeline\out\$TS"
$EXR=Join-Path $WORK "extract_realpro"
$EXU=Join-Path $WORK "extract_ulucks"
$RDIR=Join-Path $WORK "realpro_pdfs"
$UDIR=Join-Path $WORK "ulucks_pdfs"
New-Item -ItemType Directory -Force $EXR,$EXU,$RDIR,$UDIR,$OUT | Out-Null
Expand-Archive -Force $ZIPR.FullName $EXR
Expand-Archive -Force $ZIPU.FullName $EXU
Get-ChildItem $EXR -Recurse -File -Filter *.pdf | Copy-Item -Destination $RDIR -Force
Get-ChildItem $EXU -Recurse -File -Filter *.pdf | Copy-Item -Destination $UDIR -Force
& $PY -m tatemono_map.cli.pdf_batch_run --realpro-dir $RDIR --ulucks-dir $UDIR --out-dir $OUT --qc-mode warn
"OUT=$OUT"
```

#### 5) QC（住所欠損チェック）と手動補完の最小運用
MVP優先では、Realproの住所欠損は **欠損抽出 → 手動補完** で先に進みます（欠損が特定PDFに集中している場合は特に有効）。
- 現状観測では Realpro の住所欠損 109/987（約11%）のうち、108件が `レオパレスセンター小倉.pdf` に集中しています。

Realpro の `address_empty` 率を表示:

```powershell
$FINAL = Join-Path $OUT "final.csv"
$rows = Import-Csv $FINAL | ? category -eq "realpro"
$total = $rows.Count
$empty = ($rows | ? { [string]::IsNullOrWhiteSpace($_.address) }).Count
"{0}/{1} empty ({2}%)" -f $empty,$total,[math]::Round($empty/$total*100,1)
```

欠損行を `todo_realpro_missing_address.csv` に書き出し:

```powershell
Import-Csv $FINAL |
  ? { $_.category -eq "realpro" -and [string]::IsNullOrWhiteSpace($_.address) } |
  Select file,page,building_name,room,layout,floor,area_sqm,rent_man,fee_man |
  Export-Csv (Join-Path $OUT "todo_realpro_missing_address.csv") -NoTypeInformation -Encoding UTF8
```

欠損がどのPDFに集中しているか確認:

```powershell
Import-Csv $FINAL |
  ? { $_.category -eq "realpro" -and [string]::IsNullOrWhiteSpace($_.address) } |
  Group-Object file |
  Sort-Object Count -Descending |
  Select -First 10 Name,Count |
  Format-Table -Auto
```

#### 6) よくあるエラーと対処（PDF pipeline）
- `fatal: not a git repository`
  - repo 外で実行しています。`Set-Location (Join-Path $env:USERPROFILE "tatemono-map")` してから再実行してください。
- `No module named pdfplumber`
  - repo の `.venv` ではない Python を使っています。`$PY = Join-Path $REPO ".venv\Scripts\python.exe"` を使って実行してください。
- `Join-Path ... is null`
  - 別 PowerShell セッションで `$RDIR` などが消えています。`tmp\pdf_pipeline\work\<timestamp>` から対象フォルダを再設定して再実行してください。

- 実行結果は `tmp/pdf_pipeline/out/YYYYMMDD_HHMMSS` に出力されます。
- `tmp/pdf_pipeline/work/YYYYMMDD_HHMMSS` は展開・抽出の中間生成物です（最終成果物ではありません）。
- `out` 配下の主な成果物:
  - `manifest.csv`: PDFごとの入力一覧（ファイル名、SHA256、ページ数など）
  - `stats.csv`: PDFごとの件数統計（抽出件数、QC結果、除外件数など）
  - `qc_report.txt`: QC詳細（FAIL理由や除外件数）
  - `per_pdf/*.csv`: PDF単位の抽出CSV
  - `fixtures/`: QC失敗時の調査用スナップショット
  - `final.csv`: マージ済み最終CSV
- `-QcMode` の意味（既定: `warn`）:
  - `warn`: QC失敗があっても処理継続（警告のみ）
  - `strict`: QC失敗が1件でもあれば停止（非0終了）
  - `off`: QC自体をスキップ
- `FontBBox` 警告は pdfminer 由来のノイズが多く、通常は抽出結果に致命影響ありません（内容異常がないかは `qc_report.txt` / `stats.csv` で判断）。

CSV列名（final.csv / 既定）:
`category,updated_at,building_name,room,address,rent_man,fee_man,layout,floor,area_sqm,age_years,structure,file,page,raw_block`

互換モード（必要時のみ）:
- `--legacy-columns` を付与すると `source_property_name` / `room_no` / `raw_blockfile` を追加出力します。

用語（PDF batch / manual CSV 共通）:
- `building_name`: 正規化後の建物名（DB連携対象）
- `room`: 部屋番号/号室（`101` など）
- 戸建（`戸建`/`一戸建`/`貸家`/`一軒家`）は **行単位で除外** し、PDF全体は落としません。


> `C:\dev\tatemono-map` は **非推奨** です。運用は `$env:USERPROFILE\tatemono-map` に統一してください。

### よくある失敗と原因
- **DBが見つからない**
  - 別クローンを見ている、または DB 未作成。
  - `Set-Location "$env:USERPROFILE\tatemono-map"` と `SQLITE_DB_PATH=data\tatemono_map.sqlite3` を確認。
- **`scripts/run_ulucks_smartlink.ps1` が見つからない**
  - 相対パス実行でカレントディレクトリが違う、または別クローンを操作している。
  - フルパス（`$env:USERPROFILE\tatemono-map\scripts\run_ulucks_smartlink.ps1`）で実行する。
- **127.0.0.1 拒否**
  - `http.server` が起動していない、またはポート競合。
  - `-NoServe` 運用なら HTTP サーバ不要（`dist/index.html` を直接開く）。
- **`ModuleNotFoundError: tatemono_map`**
  - venv 未有効化、依存未導入、作業ディレクトリ違い。
  - `.venv\Scripts\Activate.ps1` 実行後に `python -m pip install -r requirements.txt` と `python -m pip install -r requirements-dev.txt` を実施。
- **`forbidden data detected` / `pattern=号室`**
  - `building_name` や `address` に号室/部屋番号が混入したまま `dist` 生成に進んでいるのが原因です。
  - PDF batch pipeline では `building_name` と `room` を分離して保持します。manual CSV 運用では従来どおり、建物名と号室を分離して入力してください。

---

## 最短ルート（迷ったらここだけ）
**1本の流れで迷わない運用手順です。GitHub で merge した後の同期もこれだけ。**

### Smartlink 一発実行（ingest → normalize → build → ブラウザ表示）
どの作業ディレクトリからでも次の 1 コマンドで実行できます。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\run_ulucks_smartlink.ps1" -Url 'https://ulucks.example/smartlink/?link_id=YOUR_LINK_ID&mail=user%40example.com'
```

- 既定動作: リポジトリ検出 → `git pull --ff-only` → `.venv` 作成/有効化 → 依存インストール → smartlink ingest → 正規化 → `dist` build → `http://127.0.0.1:8080/index.html` を表示
- `-NoServe` 指定時: `http.server` を起動せず、`dist/index.html` を直接開きます。
- 任意指定: `-RepoPath`, `-MaxItems`（既定200）, `-Port`（既定8080）

0) **前提：PowerShell 7.x / Windows 11**

1) **同期（GitHub→ローカル）**
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Set-Location $REPO
git pull --ff-only
git status
```

2) **起動（scripts/dev.ps1）**
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\dev.ps1"
```

3) **ローカル疎通確認（scripts/smoke.ps1）**
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\smoke.ps1"
```

3.5) **静的HTML生成（build）**
```powershell
python -m tatemono_map.render.build --output-dir dist
```

4) **変更の取り込み（コミット&push）**
- `scripts/push.ps1` で一発 push（詳細は下記の「スクリプト一覧」）

5) **よくある停止理由（sync.ps1が止まる）**
- “Untracked files: db/ や dist_tmp などがあると sync.ps1 が止まる”
  - **対処（1行）**：`db/` と `dist_tmp` 系を `.gitignore` に入れる（推奨） or `sync.ps1 -Force`（不要なら削除）
  - `tmp_ulucks_*.html` は smartlink デバッグ生成物のためコミット不要です（`dist_tmp/` など Git 管理外に出力）。

---

## 前提（必須）
- OS：**Windows 11**
- シェル：**PowerShell 7.x**
- Python：**3.11 以上**（`py -0` で確認）
- Git：インストール済み（`git --version`）

> **OneDrive 外で開発すること（必須）**
> - **統一方針**：リポジトリ実体は **`$env:USERPROFILE\tatemono-map` 固定**。
> - **理由**：OneDrive の同期/ロックが `.venv` や作業ディレクトリを不安定にし、別クローン混在を招くためです。
> - 実際の事故例：OneDrive 配下で作業すると、`Set-Location` 失敗 → `fatal: not a git repository` → venv未有効化で `ModuleNotFoundError` → build未実行で `dist/index.html` 不在、の連鎖が起きやすくなります。
> - `scripts/run_ulucks_smartlink.ps1` は OneDrive 配下を検知すると警告して停止します。

---

## 初回セットアップ
### 1) リポジトリを取得（未クローンの場合）
```powershell
git clone https://github.com/<your-org>/tatemono-map.git "$env:USERPROFILE\tatemono-map"
```

### 2) 依存インストール & 起動
初回以降は **`scripts/dev.ps1` だけでOK** です。
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\dev.ps1"
```

---

## Git運用の土台（Codex→merge→ローカルsync→開発→push）
1. **Codex / GitHub で変更 → PR → merge（main）**
2. **ローカル同期**：`scripts/sync.ps1` で **fast-forward のみ**同期
3. **開発/実行**：`scripts/dev.ps1` で起動・検証
4. **コミット & push**：`scripts/push.ps1` で一発 push

---

## スクリプト一覧（PowerShell）
### 1) 開発・起動（`scripts/dev.ps1`）
- **venv 作成/有効化** → **依存インストール** → **DBパス設定** → **uvicorn起動**
- オプション：`-InstallPytest` / `-RunTests` / `-NoReload`

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\dev.ps1" -ListenHost 127.0.0.1 -Port 8000
```

### 2) ローカル同期（`scripts/sync.ps1`）
- **未コミットがあれば停止**（`-Force` で無視可能）
- `git pull --ff-only`
- オプション：`-RunTests`

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\sync.ps1"
```

### 3) コミット & push（`scripts/push.ps1`）
- `git add -A` → `git commit -m "..."` → `git push origin main`
- **commit message は必須**

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\push.ps1" -Message "feat: add building import"
```

### 4) ローカル疎通確認（`scripts/smoke.ps1`）
- `git pull --ff-only` → サーバ起動確認 → `/health` を待機 → `/health`, `/buildings`, `/b/demo` を叩く
- **DBファイルは環境依存で差分ノイズや容量増の原因になるため Git 管理しません。**
- `DEV_SEED=true`：空DBならデモ1件を投入して `/buildings` が空にならないようにします
- `DEBUG=true`：`/debug/db` を有効化して結果表示します

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\smoke.ps1" -DevSeed -Debug
```

---

## 動作確認（/health など）
別ターミナルで実行：
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```
期待されるレスポンス：
```json
{"status": "ok", "app": "Tatemono Map", "time": "2024-01-01T00:00:00+00:00"}
```

ブラウザ確認：
- http://127.0.0.1:8000/
- http://127.0.0.1:8000/b/demo

---

## .env / secrets の扱い（重要）
- **secrets/.env はコミットしない**でください。
- 推奨：`.env.example` を作り、**安全な値だけ**をサンプルとして共有します。
- 実運用の `.env` は **ローカルだけ**に保存してください。
- **SQLITE_DB_PATH**：SQLite のファイルパスを指定（未指定なら `./data/tatemono_map.sqlite3`）。

---


## 公開禁止ルール（building単位のみ公開）
- 公開用テーブル `building_summaries` では **建物単位のみ** を扱い、号室・部屋番号・募集単位の文字列を公開してはいけません。
- `building_summaries.name` は公開名（正規化済み）として扱い、`^\s*\d{1,4}\s*[:：]\s*` のような部屋番号プレフィックスを保存しないこと。
- 元文字列は `building_summaries.raw_name` に保持し、正規化前データの追跡に使います（公開UIでは `raw_name` を直接表示しない）。
- 同一建物判定は **第一キー: 正規化済み `name`**、**補助キー: 正規化済み `address`**（完全一致または正規化一致）で行い、同一建物は canonical `building_key` 1つへ統合します。
- 統合時は `raw_name` を保持し、canonical 側で `address` 欠損がある場合は重複側の `address` で補完し、`updated_at`（なければ `last_updated`）を引き継ぎます。
- build 実行時は fail-fast バリデーションで `name` の部屋番号プレフィックス/号室表現を検出した時点で停止します。
- build 実行時は同一 `name` に複数 `building_key` が残っていても fail-fast で停止します（統合漏れを公開前に検知）。

### 正規化の実行
```powershell
python scripts/normalize_building_summaries.py
```
- 必要に応じて `--db-path` で対象DBを指定できます。スクリプトは name/address 正規化と canonical `building_key` への統合を実行します。

### 公開サイト運用手順（ingest → normalize → build）
公開HTMLは建物単位でのみ出力し、号室/参照元URL/管理会社/PDFなどの募集詳細は公開しません。

```powershell
# 1) 募集データ取り込み（DBには詳細を保持してOK）
python -m tatemono_map.ingest.run

# 2) 建物単位へ正規化・統合
python scripts/normalize_building_summaries.py

# 3) 公開HTML生成（fail-fast leak scan 付き）
python -m tatemono_map.render.build --output-dir dist
```

### Smartlink 80件を一気通貫で確認（ingest → normalize → build → index）
最短は以下の一発スクリプトです。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\run_ulucks_smartlink.ps1" -Url 'https://ulucks.example/smartlink/?link_id=YOUR_LINK_ID&mail=user%40example.com' -MaxItems 80
```

手動実行する場合のみ、従来手順を使用してください。

```powershell
# 1) Smartlink から全ページ取得（必要に応じて上限を指定）
python -m tatemono_map.ingest.ulucks_smartlink --url 'https://ulucks.example/smartlink/?link_id=YOUR_LINK_ID&mail=user%40example.com' --max-items 80

# 2) building_key 正規化・重複統合
python scripts/normalize_building_summaries.py

# 3) 公開HTML生成（漏洩スキャン実行）
python -m tatemono_map.render.build --output-dir dist

# 4) 出力確認（件数・建物ページ導線）
python -m http.server 8080 --directory dist
# ブラウザで http://127.0.0.1:8080/index.html を開く
```

- `--max-items` 未指定時は smartlink の次ページがなくなるまで取得します。
- 例: `--max-items 200` を指定すると、最大200件までで停止します。

- build は `listings` から公開許可項目のみを集計し、`(layout, area_sqm, rent_yen, maint_yen)` ごとの空室サマリーを生成します。
- 建物ページには `vacancy_total`（建物内募集合計）と、表の `vacancy_count`（サマリー行ごとの件数）を表示します。
- 「最終更新日時」は listings の最大 `updated_at`（なければ `fetched_at`）を優先し、値がなければ `building_summaries.last_updated` を使用します。

## 仕様・ドキュメント
- `docs/spec.md`
- `docs/data_contract.md`
- `docs/runbook.md`
- `docs/manual_pdf_ingest.md`

---

## FAQ
### Q1. `fatal: not a git repository`
**原因**：誤った場所で `git` を直接実行している。
**対処**：`scripts/dev.ps1` / `scripts/sync.ps1` / `scripts/push.ps1` を使う。

### Q2. `Address already in use`（ポート競合）
**原因**：8000番ポートが他プロセスで使用中。
**対処**：`-Port` を変えて起動。
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\tatemono-map\scripts\dev.ps1" -Port 8010
```

### Q3. `Activate.ps1` で venv が有効化できない
**原因**：PowerShell の実行ポリシー。
**対処**：現在のユーザーだけ許可して再実行。
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## Ulucks Phase A（smartlink 一覧のみ）

smartlink 一覧ページだけを解析して建物サマリを作る手順は `docs/ulucks_phase_a.md` を参照してください。

- detail page には遷移しません（一覧ページのみ使用）。
- smartlink 一覧ページのみをデータソースとして扱います。
- `mail`・TEL/FAX・担当者などの機微情報はログ/出力に含めない運用です。

### PowerShell one-shot（.venv の python を明示）

`pytest` コマンド未認識の環境でも確実に動かすため、`python -m pytest` と `.venv\Scripts\python.exe` を直接使います。

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Set-Location $REPO
if (-not (Test-Path ".venv\Scripts\python.exe")) { throw ".venv がありません。scripts/dev_setup.ps1 などで初期化してください。" }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pytest -q tests/test_ulucks_smartlink_phase_a.py
& .\.venv\Scripts\python.exe -m tatemono_map.ingest.ulucks_smartlink_phase_a --html tests/fixtures/ulucks/smartlink_phase_a_page_1.html tests/fixtures/ulucks/smartlink_phase_a_page_2.html --out-csv data/ulucks_phase_a_summary.csv --out-json data/ulucks_phase_a_summary.json
```

### トラブルシュート（Phase A）

- `pytest` が未認識
  - `pytest ...` ではなく `& .\.venv\Scripts\python.exe -m pytest ...` を使用。
- `ModuleNotFoundError: No module named 'selectolax'`
  - `& .\.venv\Scripts\python.exe -m pip install -r requirements.txt` と `requirements-dev.txt` を再実行。

## Ulucks smartlink 一発実行（MVP一本線）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/run_ulucks_smartlink.ps1 -Url '<smartlink>' -NoServe
```

このコマンドで `(1)詳細ページ取得 -> (2)パース -> (3)SQLite upsert -> (4)building_summaries集計 -> (5)dist生成` を順に実行します。`SQLITE_DB_PATH` 未設定時は `data/tatemono_map.sqlite3` を使います。

### DoD（最低保証）
- `dist/index.html` と `dist/b/{building_key}.html` を生成。
- index には「建物名・住所で絞り込み」を必ず表示。
- building ページは空室数・家賃レンジ・面積レンジ・間取りタイプ・最終更新を表示。
- Googleマップリンクは `address` がある場合のみ表示。

### 公開NG（dist に絶対出さない）
- 号室 / 部屋番号
- 参照元 URL
- 会社情報 / 管理会社名
- PDFリンク
