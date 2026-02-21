# tatemono-map

## 開発同期（GitHub↔ローカル）

> `setup` と `weekly_update` は開発同期には含めません。日々の同期は以下 3 コマンドのみを使います。

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -File "$REPO\sync.ps1" -RepoPath $REPO
git -C $REPO push
git -C $REPO status -sb
```

## 初回セットアップ（最初だけ）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -File "$REPO\scripts\setup.ps1" -RepoPath $REPO
```

- `scripts/setup.ps1` は `.venv` と requirements のハッシュを見て、変更がなければ `pip install` をスキップします。

## 週次運用（空室更新）

```powershell
$REPO = Join-Path $env:USERPROFILE "tatemono-map"
pwsh -File "$REPO\scripts\weekly_update.ps1" -RepoPath $REPO -DbPath "$REPO\data\tatemono_map.sqlite3"
```

- 公開データ反映が必要な場合は `scripts/publish_public.ps1` を利用してください（`data/public/public.sqlite3` の更新内容を確認してから実行）。

## What / Why
このリポジトリは、Google Maps / Street View と連携可能な「不動産データベース母艦」を作るための基盤です。  
北九州は**パイロット地域**であり、固定ターゲットではありません。  
MVP は賃貸空室データの整備を中心に進めますが、将来的には売買査定や解体比較のリード獲得にも拡張します。  
正本は `buildings` テーブルで、手動判断した canonical 値は自動上書きしません。

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
