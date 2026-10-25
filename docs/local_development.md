# ローカル開発・技術参照

2026-10-19 JST整理。Windows/PowerShellスクリプトは引き続き開発・手動補助に使用できます。ここにあるローカルDBやCSVをGCS正式正本に優先させません。Ulucks・RealPro・Mansion Reviewの通常週次収集・公開にはPC起動もローカルファイルも不要です。

## 開発環境とプレビュー

依存関係は`requirements.txt`、`requirements-dev.txt`と`pyproject.toml`を参照します。クラウド関連の検証依存は`requirements-cloud-test.txt`、GCSクライアント等は`requirements-cloud.txt`です。

既存Windows補助スクリプト:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev_setup.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev_dist.ps1
```

プレビューのデータはローカルの公開スナップショットであり、本番正本の最新性を保証しません。Pagesとの照合方法は[本番Runbook](runbook.md)を参照します。旧`weekly_update`/`run_all_latest`/`publish_public`のローカル手順は[旧README全文](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/README.md)に保存しています。本番更新の通常手順として実行しません。

## フロント設定・技術情報の参照

- 表示テーマは`?theme=default|ph|mercari`の有効なクエリがビルド時既定値に優先します。単一ページの表示上書きです。
- 現行Pages Workflowの既定テーマは`mercari`、住所表示は`full`（手動dispatchで指定可能）。手動Workflow入力等は[deploy_pages.yml](../.github/workflows/deploy_pages.yml)を確認します。今回の文書整理でUIや設定は変更していません。
- v2一覧は`data/buildings.v2.min.json`を使い、必要時に`data/buildings.json`へフォールバックします。いずれも公開派生データです。
- Google Maps Embed、favicon、住所表示モード、SEO/Search Console、築年数補正、入居可能日・家賃・構造のSQL、gzip/br確認、ローカルHTTP診断の詳細は下記固定版で全文参照できます。

| 技術情報 | 保存先 |
| --- | --- |
| テーマ・Maps・favicon・SEO・築年数・availability・SQL・ローカル確認 | [旧README全文](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/README.md) |
| ローカル更新・UI検証・Mansion Review/Orient・correction手順 | [旧Runbook全文](https://github.com/aik38/tatemono-map/blob/03be5e82c5dcc65f1d4960f0da421024cefa3e27/docs/runbook.md) |
| CSV列・単位・NULL・age/structureの集約契約 | [現行仕様・データ契約](spec.md) |
| フロントの過去変更 | [frontend履歴](frontend_versions.md) |
| 手動PDF・訂正台帳 | [手動PDF](manual_pdf_ingest.md) / [correction CSV](building_corrections_csv.md) |

固定版の技術メモと当時の運用判断は区別します。現行の正本所在・自動公開・安全条件は[spec](spec.md)と[データフロー](data_flow_and_sources_of_truth.md)を優先し、旧公開ID制限、ローカルDBの本番上書き、初期接続の再実行へ戻しません。
