# 建物マップ / tatemono-map

建物を恒久的な資産として管理し、賃貸・分譲の募集情報を同じcanonical建物に紐づける不動産データ基盤です。北九州を起点に、地図・ストリートビューと相談導線へ接続します。

本番サイト: https://www.tatemono-map.com/

## 現在の本番構成

2026-10-19 JST文書整理時点。Ulucksは対象会社を自動判定し、北九州全域を収集するクラウド経路です。

**Cloud Scheduler → Cloud Run → Ulucks PDF取得・private保存 → 解析・名寄せ・QC → SQLite正式正本更新 → GCS正式リリース → GitHub Actions → GitHub Pages**

- 通常週次: 月曜04:00 JST（`0 4 * * 1`, `Asia/Tokyo`）。Job名は旧PoC名の `tatemono-collection-poc` を継続使用。
- Windows PCやChatGPT Workの常時起動、ローカルSQLite/PDF/CSV/ZIPは通常運用に不要です。
- 初回の実収集・正本更新・本番公開は成功済みです。定刻無人実行の成功は別の証拠で確認します。文書整理時点では2026-10-19 04:00 JSTの実行前です。
- Pagesは毎時23分に未公開リリースを確認し、変更なしの定時チェックでは重いビルドを省略します。

## 正本と公開の境界

本番の正本は **GCS `state/current.json` がgeneration・SHA-256付きで指すSQLite** です。建物だけでなく募集・履歴・alias・ソース別current snapshotを保持します。

| データ | 役割 |
| --- | --- |
| `masters/<run>.sqlite3` | GCS上の正式正本。建物の同一性は`buildings`で管理 |
| `private-runs/<run>/` | PDF原本・解析結果・保留資料・取得証跡 |
| `public/releases/<run>/public.sqlite3` | 正式正本から作る公開専用の派生DB |
| 検索JSON・HTML・サイトマップ | 公開DBから生成する配信成果物 |
| ローカルDB・CSV・ZIP | 開発・手動補助・過去移行資料。本番正本に優先しない |

PDFは取り込み後もprivate GCSへ保存する実装です。PDF原本の保存と、解析した数値・文字列のSQLite保存は両立します。manifest/evidenceから会社・run・元PDF・generation・SHA-256を追跡できます。現存PDF総数・保存期間・ライフサイクルは今回未確認で、永久保存は保証しません。

## 採用・自動公開・建物保護

- 解析・名寄せ時点で精査し、高信頼データを正式採用。曖昧・異常な未採用行はprivateに保留します。
- **正式採用建物は原則自動公開**。明示的除外は`hidden_from_public`で管理し、毎週の人間による追加公開承認は不要です。
- 過去の公開DBは欠落防止の比較用であり、新規建物の公開許可リストではありません。
- 建物ID・正式名称・住所・既存URL・canonical・履歴を保護し、募集0件でも建物ページを維持します。
- 名称・住所の一致だけで異なるIDを検索から除外しません。ページ統合は整合する明示的canonical aliasに限定します。
- 賃貸優先順位は **Ulucks ＞ RealPro ＞ Mansion Review賃貸**。Mansion Review分譲は独立系統です。
- RealPro・Mansion Reviewには既存の取り込み・集約機能がありますが、Ulucksと同じGCP週次収集まで完成したとは扱いません。

## 読む順序

1. [PLAN](PLAN.md): 目的・運用方針・優先順位
2. [spec](docs/spec.md): 守るべき実装契約
3. [データフローと正本](docs/data_flow_and_sources_of_truth.md): 原本から公開までの役割
4. [Cloud構成](cloud/README.md) / [本番Runbook](docs/runbook.md): 通常運用・確認・障害対応
5. [データ契約](docs/data_contract.md) / [CIと公開](docs/ops_ci_testing.md) / [WBS](docs/wbs.md)
6. [ローカル開発・技術参照](docs/local_development.md) / [文書索引](docs/README.md)

旧Windows手順・初期PoC・当時の技術情報の全文は[履歴索引](docs/archive/README.md)から固定コミットで参照できます。既存PowerShellスクリプトは手動補助として残っていますが、クラウド本番の必須手順ではありません。
