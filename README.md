# tatemono-map

## 開発同期（GitHub↔ローカル）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\sync.ps1" -RepoPath $REPO
git -C $REPO status -sb
git -C $REPO push
```

## 初回セットアップ（最初だけ）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\setup.ps1" -RepoPath $REPO
```

- `scripts/setup.ps1` は冪等（idempotent）です。
- `.venv` と requirements フィンガープリント（ハッシュ）が前回と同じ場合、`pip install` / `pip install -e` をスキップします。

## 週次運用（空室更新）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\weekly_update.ps1" -RepoPath $REPO -DbPath "$REPO\data\tatemono_map.sqlite3"
```

- 週次は 1 コマンドで再現可能です。
- `weekly_update` は `buildings` を再構築しません（空室取り込み + 建物同定 + review CSV + 公開生成）。
- review CSV は `tmp/review/` に出力されます（`new_buildings` / `suspects` / `unmatched_listings`）。

## 公開反映（必要時）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -NoProfile -ExecutionPolicy Bypass -File "$REPO\scripts\publish_public.ps1" -RepoPath $REPO
```

## What / Why
このリポジトリは、Google Maps / Street View（ストリートビュー）と連携可能な「不動産データベース母艦」を作るための基盤です。  
北九州は**パイロット地域**であり、固定ターゲットではありません。  
MVP は賃貸空室データの整備を中心に進めますが、将来的には売却査定や解体比較のリード獲得にも拡張します。  
正本（Canonical Source of Truth）は SQLite の `buildings` テーブルです。

## Non-goals（このPRDでやらないこと）
- UI テンプレートや見た目の最適化を先行しない。
- `buildings` の canonical 項目を自動更新しない。
- 旧来の `buildings_master` 再構築フローを現行運用に戻さない。

## Docs
- ドキュメント入口: [docs/README.md](docs/README.md)
- 方針（唯一の運用方針）: [PLAN.md](PLAN.md)
- 仕様（役割分担・禁止事項・更新方針）: [docs/spec.md](docs/spec.md)
- 運用手順: [docs/runbook.md](docs/runbook.md)
- 工程管理（Phase/DoD）: [docs/wbs.md](docs/wbs.md)
