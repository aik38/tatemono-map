# tatemono-map

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/setup.ps1 -RepoPath "$PWD"
pwsh -NoProfile -ExecutionPolicy Bypass -File ./sync.ps1 -RepoPath "$PWD"
pwsh -NoProfile -ExecutionPolicy Bypass -File ./push.ps1 -RepoPath "$PWD"
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/weekly_update.ps1 -RepoPath "$PWD" -DbPath ./data/tatemono_map.sqlite3
```

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
