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


## 4-1. mansion-review 推奨運用（全ページ自動収集）
- **基本は `run_mansion_review_crawl.ps1` を使った自動収集**。小倉北区/門司区の 1 ページ目〜最終ページまで巡回し、一覧カードを構造化して CSV 化する。
- `-MaxPages 0` の場合は 1 ページ目のページネーションから最終ページを自動推定する。
- `stats.json` で `pages_total` / `rows_total` / `zero_extract_pages` を確認する。
- `zero_extract_pages` が 1 件でもある場合は `debug/*.html` を見てセレクタ不一致を調査する。

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
