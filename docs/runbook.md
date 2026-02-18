# Runbook（手動一次資料 → CSV → building master 合算の正本）

## 0. 目的と対象
- 対象は **手動一次資料（PDF ZIP / 保存HTML）を CSV 化し、building master を作る運用** のみ。
- 既存 Python 処理は変更せず、**I/O 契約と入口スクリプトを固定**して再現性を担保する。
- 公開禁止情報（号室、参照元URL、管理会社情報、認証情報、生PDF/ZIP）を公開物へ出さない。

## 1. 実行場所非依存の repo 固定
PowerShell はどの CWD からでも、必ず repo パスをこの形で定義する。

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
```

- `sync.ps1` / `push.ps1` / `scripts/*.ps1` は `-RepoPath` を受け取り、repo 妥当性（`.git` と `pyproject.toml`）を検証する。
- `-RepoPath` 未指定時は `Join-Path $env:USERPROFILE "tatemono-map"` を既定値とする。

## 2. 固定 I/O 契約（ディレクトリ）

```text
tmp/
  manual/
    inputs/
      pdf_zips/                           # 手動入手した PDF ZIP（Ulucks / RealPro）
      html_saved/                         # mansion-review 等の保存 HTML
      buildings_master/
        buildings_master_primary.csv      # 合算の主系入力（固定名）
        buildings_master_secondary.csv    # 合算の従系入力（固定名）
    outputs/
      mansion_review/
        <timestamp>/mansion_review_<timestamp>.csv                 # 保存HTML→CSV
        <timestamp>/mansion_review_list_<timestamp>.csv            # 自動巡回(list)→CSV
        <timestamp>/stats.json
        <timestamp>/debug/*.html
      buildings_master/
        buildings_master.csv              # 合算の最終成果物（固定名）
  pdf_pipeline/
    work/                                 # PDF 一時作業領域
    out/
      <timestamp>/final.csv               # PDF ZIP → CSV 成果物
```

## 3. スクリプトと既定 I/O（固定）
- `scripts/run_pdf_zip_latest.ps1`
  - 入力: `Downloads` の最新 `リアプロ-*.zip` / `ウラックス-*.zip`（必要に応じて `tmp/manual/inputs/pdf_zips/` に保管）
  - 出力: `tmp/pdf_pipeline/out/<timestamp>/final.csv`
- `scripts/run_mansion_review_html.ps1`
  - 入力: `tmp/manual/inputs/html_saved/`
  - 出力: `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_<timestamp>.csv`
- `scripts/run_mansion_review_crawl.ps1`
  - 入力: city_id/kind 指定（HTTP 自動巡回。手動保存HTMLは不要）
  - 出力: `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_list_<timestamp>.csv` + `stats.json` + `debug/*.html`
- `scripts/run_merge_building_masters.ps1`
  - 入力: `tmp/manual/inputs/buildings_master/buildings_master_primary.csv` + `buildings_master_secondary.csv`
  - 出力: `tmp/manual/outputs/buildings_master/buildings_master.csv`

## 4. 迷わない実行手順（Quickstart と同一）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\setup.ps1") -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\run_pdf_zip_latest.ps1") -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\run_mansion_review_html.ps1") -RepoPath $REPO
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\run_mansion_review_crawl.ps1") -RepoPath $REPO -CityIds "1616,1619" -Kinds "mansion,chintai" -Mode list -MaxPages 0
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "scripts\run_merge_building_masters.ps1") -RepoPath $REPO
```


## 4-1. データ収集（mansion-review）
対象は `mansion-review.jp` の city 一覧（分譲=`mansion` / 賃貸=`chintai`）。

- URL 1ページ目: `https://www.mansion-review.jp/{kind}/city/{city_id}.html`
- URL 2ページ目以降: `https://www.mansion-review.jp/{kind}/city/{city_id}_{n}.html`（`n>=2`）
- `kind`: `mansion` または `chintai`
- `city_id` 例: `1619=小倉北区`, `1616=門司区`

目視確認用 URL（そのままブラウザで確認可）:

- 540件 分譲マンション 小倉北区
  - https://www.mansion-review.jp/mansion/city/1619.html
  - https://www.mansion-review.jp/mansion/city/1619_2.html
  - https://www.mansion-review.jp/mansion/city/1619_3.html
- 270件 分譲マンション 門司区
  - https://www.mansion-review.jp/mansion/city/1616.html
  - https://www.mansion-review.jp/mansion/city/1616_2.html
  - https://www.mansion-review.jp/mansion/city/1616_3.html
- 2049件 賃貸物件 小倉北区
  - https://www.mansion-review.jp/chintai/city/1619.html
  - https://www.mansion-review.jp/chintai/city/1619_2.html
  - https://www.mansion-review.jp/chintai/city/1619_3.html
- 477件 賃貸物件 門司区
  - https://www.mansion-review.jp/chintai/city/1616.html
  - https://www.mansion-review.jp/chintai/city/1616_2.html
  - https://www.mansion-review.jp/chintai/city/1616_3.html

使用スクリプト:

- PowerShell wrapper: `scripts/run_mansion_review_crawl.ps1`
- 本体: `scripts/mansion_review_crawl_to_csv.py`
- 出力先:
  - `tmp/manual/outputs/mansion_review/<timestamp>/mansion_review_list_<timestamp>.csv`
  - `tmp/manual/outputs/mansion_review/<timestamp>/stats.json`
  - 結合出力: `tmp/manual/outputs/mansion_review/combined/`

### Quickstart（確実に通った一発コマンド）
PowerShell 7.5.4 前提。`$env:USERPROFILE\tatemono-map` を repo パスとして固定し、4ジョブを順番に実行する。

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

### 検算（収集できたか確認）
最新4CSVをまとめて件数と内訳を確認する。実行例として `FILES = 4`、`TOTAL ROWS = 3340` が得られる。

> 重複チェックは `building_url` ではなく `detail_url` を使うこと（CSV列に `building_url` は無い）。

```powershell
$ErrorActionPreference="Stop"
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$root = Join-Path $REPO "tmp\manual\outputs\mansion_review"

$csvs = Get-ChildItem $root -Recurse -File -Filter "mansion_review_list_*.csv" |
  Where-Object { $_.Name -notlike "*COMBINED*" } |
  Sort-Object LastWriteTime -Desc | Select-Object -First 4

$all = foreach ($c in $csvs) { Import-Csv $c.FullName }

"FILES = $($csvs.Count)"
"TOTAL ROWS = $($all.Count)"
$all | Group-Object kind, city_id | Sort-Object Name | Select-Object Count, Name

$dupGroups = $all | Group-Object { (($_.detail_url ?? "")).Trim() } |
  Where-Object { $_.Name -ne "" -and $_.Count -gt 1 }

"dup detail_url groups = $($dupGroups.Count)"
"unique detail_url = $(@($all | Where-Object detail_url | Select-Object -Expand detail_url | Sort-Object -Unique).Count)"
```

例: `dup detail_url groups = 750` / `unique detail_url = 2557`

### 結合CSVの作成
最新4CSVを結合し、`combined/mansion_review_list_COMBINED_YYYYMMDD_HHMMSS.csv` を作成する。

```powershell
$ErrorActionPreference="Stop"
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$root = Join-Path $REPO "tmp\manual\outputs\mansion_review"
$outDir = Join-Path $root "combined"
New-Item -ItemType Directory -Force $outDir | Out-Null

$csvs = Get-ChildItem $root -Recurse -File -Filter "mansion_review_list_*.csv" |
  Where-Object { $_.Name -notlike "*COMBINED*" } |
  Sort-Object LastWriteTime -Desc | Select-Object -First 4

$all = foreach ($c in $csvs) { Import-Csv $c.FullName }

$out = Join-Path $outDir ("mansion_review_list_COMBINED_{0}.csv" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$all | Export-Csv $out -NoTypeInformation -Encoding utf8BOM
"COMBINED = $out"
"TOTAL ROWS = $($all.Count)"
```

### ユニーク化（detail_url で建物マスター化）
`detail_url` が空の行を除外し、`detail_url` でユニーク化した master CSV を作成する。

```powershell
$ErrorActionPreference="Stop"
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
$root = Join-Path $REPO "tmp\manual\outputs\mansion_review"
$outDir = Join-Path $root "combined"
New-Item -ItemType Directory -Force $outDir | Out-Null

$csvs = Get-ChildItem $root -Recurse -File -Filter "mansion_review_list_*.csv" |
  Where-Object { $_.Name -notlike "*COMBINED*" } |
  Sort-Object LastWriteTime -Desc | Select-Object -First 4

$all = foreach ($c in $csvs) { Import-Csv $c.FullName }

$uniq = $all |
  Where-Object { ($_.detail_url ?? "").Trim() -ne "" } |
  Sort-Object detail_url -Unique

$out = Join-Path $outDir ("mansion_review_master_UNIQ_{0}.csv" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$uniq | Export-Csv $out -NoTypeInformation -Encoding utf8BOM

"UNIQ OUT = $out"
"UNIQ ROWS = $($uniq.Count)"
$uniq | Group-Object kind, city_id | Sort-Object Name | Select-Object Count, Name
```

例: `UNIQ ROWS = 2557`（`kind,city_id` 内訳はコマンド出力で確認）

### 補足（運用上の注意）
- `cache_hit=True/False` はキャッシュ利用の有無。`False` は失敗ではなく「キャッシュ未命中でWeb取得した」という意味。
- `MaxPages=0` は自動検出モード。現状は誤検出リスクがあるため、当面は `MaxPages` 明示指定を推奨。
- 実測ページ数 `7/14/12/52` は 2026-02-18 時点の目安で、将来増減しうる。

### 手動保存HTMLを使う場合
- 既存の `run_mansion_review_html.ps1` は互換維持されており利用可能。
- 手動保存するなら **HTML のみ** で十分（完全保存でも動くが不要）。

## 5. GitHub ↔ ローカル同期（repo 外から実行可）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "sync.ps1") -RepoPath $REPO
```

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $REPO "push.ps1") -RepoPath $REPO -Message "your commit message" -SensitiveColumnPolicy strict
```

## 6. 事故防止ガード
- `.gitignore` で `secrets/**`, `.tmp/**`, ルート `/*.csv`, `tmp/**（.gitkeep と tmp/manual/README.md のみ例外）` を無視。
- `scripts/git_push.ps1` が push 前に以下を検査。
  - tracked に `secrets/**` / `.tmp/**` / `tmp/**（.gitkeep と tmp/manual/README.md 以外）` がある → **失敗**
  - tracked にルート `*.csv` がある → **失敗**
  - CSV ヘッダに `room_no`, `unit`, `号室`, `source_url` などがある → `warn` or `strict`


## 6-1. tmp/manual 配下の扱い（tracked 許可/禁止）
- `tmp/manual/README.md` はガイダンス文書として **tracked 許可**。
- `tmp/manual` 配下の生成物（CSV/zip/html など）は **tracked 禁止**。
- 固定ディレクトリ維持用の `.gitkeep` は tracked 許可。

## 7. 事故った時の復旧手順

### 7-1. 誤って追跡されたファイルを index から外す
```powershell
git rm --cached -r secrets .tmp tmp
git rm --cached *.csv
```

### 7-2. 直前コミットを戻す（未 push の場合）
```powershell
git reset --soft HEAD~1
```

### 7-3. すでに push 済みの場合
- 対象コミットを `git revert` して履歴で打ち消す。
- 漏えいした認証情報は **即時 rotate**（API key / password / token）。
- 公開物に混入した URL や号室情報は削除し、再生成・再配布する。

## 8. QC（最低限）
```powershell
$csv = "tmp\pdf_pipeline\out\<timestamp>\final.csv"
$rows = Import-Csv $csv
"building_name empty = {0}/{1}" -f (($rows | ? { [string]::IsNullOrWhiteSpace($_.building_name) }).Count), $rows.Count
"address empty      = {0}/{1}" -f (($rows | ? { [string]::IsNullOrWhiteSpace($_.address) }).Count), $rows.Count
```

- `stats.csv` の `status / warning_count / reasons` を必ず確認。
- 欠損率が高い場合は一次資料の品質・抽出ルールを優先確認する。
