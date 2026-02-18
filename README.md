# tatemono-map

`tatemono-map` は、**建物DB（`building_summaries`）を静的Webに変換し、GitHub Pages で公開し、Google Maps / Street View に導線をつなぐためのMVP**です。

## MVP Flow（最重要）
`building_summaries DB` → `dist 生成` → `GitHub Pages 公開` → `Google Maps / Street View リンク`

## 公開禁止データ（最初に確認）
以下は **public 配布物（`dist/`・Pages）へ出してはいけません**。

- 号室（room/unit）
- 参照元URL（source_url / reference_url など）
- 管理会社情報
- 元PDF / ZIP / 保存HTML
- 個人情報（氏名・電話・メール等）

理由: MVP の公開目的は「建物単位の情報提供」であり、**個別住戸・出所・個人情報を含めると情報漏えい/契約違反リスクが高い**ためです。

---

## ドキュメントの正本（役割分担）
- 仕様の正本: [`docs/spec.md`](docs/spec.md)
- 運用手順の正本: [`docs/runbook.md`](docs/runbook.md)
- 工程・進行管理の正本: [`docs/wbs.md`](docs/wbs.md)

README は「入口（最短手順）」に限定し、詳細運用は runbook を参照してください。

---

## Quickstart（PowerShell 7 / コピペ用・CWD非依存）

### 0) Repo パスを固定
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"   # 例: C:\Users\OWNER\tatemono-map
```

### 1) GitHub と同期（推奨: sync.ps1）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\sync.ps1" -RepoPath $REPO
```

### 2) dist を生成（MVP 最短本線）
```powershell
python -m tatemono_map.render.build --db-path "$REPO\data\public\public.sqlite3" --output-dir "$REPO\dist" --version all
```

### 3) 生成物をローカルで確認
```powershell
Start-Process "$REPO\dist\index.html"
```

### 4) 公開先（GitHub Pages）
- 公開対象は `dist/` 生成物です（公開方法の詳細は runbook / リポジトリ設定に従う）。
- Pages の運用詳細は [`docs/runbook.md`](docs/runbook.md) を参照。

---

## 日次運用（一次資料 → CSV → 合算）は runbook へ
この README では入口のみ示します。詳細フローは [`docs/runbook.md`](docs/runbook.md) が正本です。

- `scripts/run_pdf_zip_latest.ps1`
- `scripts/run_mansion_review_html.ps1`
- `scripts/run_merge_building_masters.ps1`

### Ulucks / RealPro（pdf_pipeline）成果物の場所
- 出力ルート: `tmp/pdf_pipeline/out/<timestamp>/`
- 主要成果物: `final.csv`, `manifest.csv`, `qc_report.txt`, `stats.csv`, `per_pdf/`
- `final.csv` は **空室リスト（抽出結果の集約）** であり、建物DBそのものではありません（建物DB化は runbook の「次の工程」を実施）。

```powershell
# 最新 out を 1 発で特定
$latestOut = Get-ChildItem (Join-Path $REPO "tmp\pdf_pipeline\out") -Directory |
  Sort-Object LastWriteTime -Desc | Select-Object -First 1 -ExpandProperty FullName
$latestOut
```

### mansion-review 一覧収集（最短 Quickstart 抜粋）
詳細手順は runbook の「データ収集（mansion-review）」を参照してください。

- runbook: [`docs/runbook.md#4-1-データ収集mansion-review`](docs/runbook.md#4-1-データ収集mansion-review)

```powershell
$ErrorActionPreference="Stop"
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$PS1  = Join-Path $REPO "scripts\run_mansion_review_crawl.ps1"

# 分譲: 1616=7p, 1619=14p / 賃貸: 1616=12p, 1619=52p
$jobs = @(
  @{CityIds="1616"; Kinds="mansion"; MaxPages=7},
  @{CityIds="1619"; Kinds="mansion"; MaxPages=14},
  @{CityIds="1616"; Kinds="chintai"; MaxPages=12},
  @{CityIds="1619"; Kinds="chintai"; MaxPages=52}
)

foreach ($j in $jobs) {
  pwsh -NoProfile -ExecutionPolicy Bypass -File $PS1 `
    -RepoPath $REPO `
    -CityIds  $j.CityIds `
    -Kinds    $j.Kinds `
    -Mode     "list" `
    -SleepSec 0.7 `
    -MaxPages $j.MaxPages
}
```

- 出力ルート: `tmp/manual/outputs/mansion_review/<timestamp>/`
- 主要成果物: `mansion_review_list_<timestamp>.csv`, `stats.json`
- 合算/ユニーク化成果物: `tmp/manual/outputs/mansion_review/combined/`
  - `mansion_review_list_COMBINED_<timestamp>.csv`
  - `mansion_review_master_UNIQ_<timestamp>.csv`
- `cache_hit=True/False` は成功/失敗ではなく「キャッシュ命中」の有無です。`False` が多くても `rows > 0` であれば収集成功です。

### 次工程（空室リスト → 建物DBの入力CSV）
- runbook の「次の工程：空室リスト → 建物DB（重複なし）」を実施。
- 一発実行（latest 自動検出）:

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\run_buildings_master_from_sources.ps1") -RepoPath $REPO
```

---

## Git sync / push（CWD非依存）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\sync.ps1" -RepoPath $REPO
```

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\push.ps1" -RepoPath $REPO -Message "docs: update README" -SensitiveColumnPolicy strict
```

`push.ps1` は push 前にガードを実行し、以下を検知すると停止します。
- tracked の `secrets/**`, `.tmp/**`, `tmp/**`（例外は後述）
- tracked のリポジトリ直下 `*.csv`
- CSV ヘッダのセンシティブ列（strict時）

### tracked 例外（README / .gitignore / pushガードで一致）
- `tmp/manual/README.md` は tracked 可
- `tmp/manual` / `tmp/pdf_pipeline` の既定 `.gitkeep` は tracked 可（ディレクトリ維持用）
- 上記以外の `tmp/**` 生成物（CSV / zip / html 等）は tracked 不可

---

## Troubleshooting（詰まりやすいポイントだけ）

### 1) `pwsh -File ...` で「script not recognized」
多くは **ファイル未存在 / 未pull / パス違い** です。以下で切り分けます。

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
Test-Path "$REPO\sync.ps1"
Test-Path "$REPO\push.ps1"
Test-Path "$REPO\scripts\git_push.ps1"
```

1つでも `False` なら:
```powershell
git -C $REPO pull --ff-only
Get-ChildItem "$REPO\scripts" | Select-Object Name
```

### 2) push が `Forbidden tracked files detected` で落ちる
まず診断:
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\git_doctor.ps1" -RepoPath $REPO
```

復旧（index から除外）:
```powershell
git -C $REPO rm --cached <対象パス>
```

例: `tmp` の誤追跡をまとめて外す
```powershell
git -C $REPO rm --cached -r tmp
```

残すべきもの:
- `tmp/manual/README.md`
- `tmp/manual` / `tmp/pdf_pipeline` の既定 `.gitkeep`

消すべきもの（tracked禁止）:
- `tmp/**` の生成CSV / zip / html など
- `secrets/**`, `.tmp/**`, ルート `*.csv`

### 3) 誤パス（例: `C:\Users\OWNER\AI\tatemono-map`）を使ってしまう
```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$REPO
Test-Path "$REPO\.git"
Test-Path "$REPO\pyproject.toml"
Get-ChildItem (Join-Path $env:USERPROFILE "*") -Directory | Where-Object Name -like "*tatemono*"
```

`$REPO\.git` と `$REPO\pyproject.toml` が両方 `True` になるパスだけを使ってください。
