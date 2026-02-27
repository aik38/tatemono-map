# 週次運用カード（A4 / 1枚）

目的: **MVP運用を「毎週一発コマンド」で固定**し、毎週の確認漏れを防ぐ。

---

## 0. 事前準備（1分）
- ローカル repo を最新化
- PowerShell で実行（`pwsh`）

## 1. 同期（必須）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync.ps1
```

## 2. 本番反映（唯一の正解フロー）
```powershell
$REPO = "C:\path\to\tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\run_to_pages.ps1" -RepoPath $REPO
```
- ingest → public DB 更新 → commit/push までを一括実行

## 3. KPI控え（週次ログへ転記）
- ingest 側: `attached_listings`, `unresolved`
- public 側: `sum(vacancy_count)`（`building_summaries`）

## 4. Actions 成功確認
- GitHub Actions: **Deploy static site to GitHub Pages = Success**

## 5. 実機確認（最低限）
- スマホでトップ表示・主要導線を確認
- シークレットウィンドウでキャッシュ影響を除外して確認

## 6. unmatched 簡易確認（深追いしない）
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\unmatched_report.ps1 -RepoPath $REPO
```
- 週次では **reason の偏り確認だけ**を実施
- 住所/名称の個別深掘りは原則しない（必要時のみ別タスク化）

## 7. 週次ログ 1行フォーマット例
```text
2026-02-27 | run_to_pages:ok | attached=1234 unresolved=56 public_sum=789 | pages=success | mobile+incognito=ok | unmatched_top_reason=NAME_MISMATCH(21)
```

---

### NG（やらないこと）
- `run_to_pages.ps1` の代替フローを作らない
- `dist/` や `data/tatemono_map.sqlite3` を配信物として commit しない
- unmatched を毎週フル調査しない（最小PDCAで回す）
