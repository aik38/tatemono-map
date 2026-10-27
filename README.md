# 建物マップ / tatemono-map

北九州を起点とする、**建物単位の不動産情報基盤**です。建物IDを恒久的に管理し、賃貸募集と分譲販売を同じ建物に紐付け、地図・建物詳細・LINE等の相談導線につなげます。

**本番サイト:** https://www.tatemono-map.com/

> 現行運用の文書基準日: **2026年10月25日 JST**。公開件数はその日の実績であり固定値ではありません。正本と稼働状態の確認方法は[運用手順](docs/runbook.md)を参照してください。

## いま動いている仕組み

**GCP Cloud Scheduler → 3つのCloud Run Job → 原本の非公開GCS保存 → 解析・名寄せ・品質判定 → SQLite正式正本 → GCSリリース → GitHub Actions → GitHub Pages → 実Web照合**

| 情報源 | 本番Cloud Run Job | 週次起動（JST） | 収集対象 |
| --- | --- | --- | --- |
| Ulucks | `tatemono-collection-poc` | 木曜14:00 | 対象管理会社の自動判定、北九州全域のPDF |
| RealPro | `tatemono-realpro-weekly` | 木曜14:05 | 福岡県内で取得可能な対象管理会社のPDF |
| Mansion Review | `tatemono-mansion-weekly` | 木曜14:10 | 設定済み35市区町村の賃貸・分譲情報 |

週次基準は直近の木曜14:00 JST。RealProは当該基準以降のUlucks、Mansion ReviewはUlucks・RealProの終了を待ちます。

- **3情報源の週次クラウド起動・収集・統合・公開経路は実装・設定済みです。** 2026年10月29日から木曜14:00／14:05／14:10（Asia/Tokyo）に起動します。初回の旧月曜スケジュール（2026年10月26日）の全対象実行結果は別途実測確認対象です。Scheduler有効化を全対象の実収集成功とは読み替えません。
- RealProは当該週のUlucks実行終了待ち、Mansion Reviewは両上流Jobの実行終了待ちを行います。**終了と成功は異なります**。障害・部分成功・未処理は個別に確認します。
- Windows PC、Chrome、ChatGPT Work、ローカルSQLite/PDF/CSVは通常運用の必須条件ではありません。ローカル補助資料の削除前には未同期原本・独自修正・認証復旧資料を確認してください。

## 守るべき原則

1. **既存データを壊さない。** canonical建物ID、名称・住所、URL、alias、履歴を保護する。
2. **重複建物を増やさない。** 一意の根拠がない名寄せ・新規採用は保留する。
3. **不正確な情報を公開しない。** 異常・曖昧な入力は非公開で証拠を保持する。

賃貸は建物単位で **Ulucks ＞ RealPro ＞ Mansion Review** の優先順位を適用し、異なるソースの賃貸明細を水増し合算しません。Mansion Reviewの分譲販売は賃貸と独立です。正式採用の非hidden建物は原則として自動公開します。

## 直近の本番公開実績（2026年10月25日）

| 指標 | 実績 |
| --- | ---: |
| 公開建物 | **8,562棟** |
| 賃貸募集 | **11,655件** |
| 分譲販売 | **966件**（限定改善作業の完了報告値） |
| Mansion Review保留401行の限定再判定 | 281行採用・120行保留・新規117棟 |

正式リリース: `20261024T211537Z-234490f79001`。当該リリースのWeb反映は [Pages #40180748608](https://github.com/aik38/tatemono-map/actions/runs/40180748608) で成功し、[公開release marker](https://www.tatemono-map.com/cloud_release.json) で建物・賃貸件数を照合できます。分譲件数は運用側の確認値として扱います。

**本番の正本はGCS `state/current.json` が世代とハッシュ付きで指すSQLite** です。GitHubのソース・WebのJSON・ローカルDBは正本ではありません。

## 主要ドキュメント（この6ファイルが現行運用の入口）

| 文書 | 目的 |
| --- | --- |
| [README.md](README.md) | ここ。目的・状態・参照先 |
| [PLAN.md](PLAN.md) | 開発優先順位・運用方針 |
| [docs/spec.md](docs/spec.md) | データ契約・同定・採否と公開の制約 |
| [docs/data_flow_and_sources_of_truth.md](docs/data_flow_and_sources_of_truth.md) | 3情報源・GCS・正本・Pagesの構造 |
| [docs/runbook.md](docs/runbook.md) | 通常週次・確認・障害・安全な復旧 |
| [docs/README.md](docs/README.md) | 文書索引・専門資料・歴史資料 |

整理前の文書一式は[2026-10-25の固定履歴](docs/archive/README.md)から復元できます。詳細が必要なときだけ専門資料を参照し、同じ運用仕様を複数箇所へ重複記載しないでください。
