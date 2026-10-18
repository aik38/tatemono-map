# データフローと正本

2026-10-19 JST更新。本番の入口はGCS `state/current.json`です。ローカルパスの有無でクラウドの通常週次処理は変わりません。

## 原本から公開まで

| 段階 | 保存先・実体 | 意味と取り扱い |
| --- | --- | --- |
| 取得原本 | private GCSのPDF・manifest・evidence | 取得時の証拠。解析しても原本を保存する実装 |
| 解析・構造化 | `parsed-rows.json`、作業中の`master_import.csv` | PDFから抽出した建物名・住所・募集条件。全行が正式採用されるわけではない |
| 精査・内部保留 | `review-rows.csv`、private診断、正本内raw履歴等 | 曖昧・異常・未採用の記録。Webへ流さない |
| 正式採用と履歴 | HEADの`master`参照が指すSQLite | canonical、募集、alias、由来、run、source別currentを保持 |
| 公開派生DB | HEADの`public`参照が指すSQLite | 非hidden正式採用建物と安全な集約・aliasだけを生成 |
| 配信成果物 | 検索JSON・HTML・サイトマップ・release marker | Pagesが公開DBから生成し、本番Webで検証 |

通常経路は **Scheduler → Cloud Run fresh収集 → 原本保存 → 解析・名寄せ・QC → 正本/公開DB保存・HEAD CAS更新 → Pagesリリース確認 → ビルド・デプロイ・実Web照合** です。WindowsでPDFやZIPを置く工程は必須ではありません。

## GCS上の対応

```text
state/current.json
masters/<release-run>.sqlite3
public/releases/<release-run>/public.sqlite3
backups/<collection-run>.sqlite3
private-runs/<collection-run>/
  companies/<company-id>/
    pdf/000.pdf
    pdf/001.pdf
    parsed-rows.json
    review-rows.csv
  company-<company-id>-manifest.json
  company-<company-id>-evidence.json
  company-<company-id>-result.json
```

これは主な全社バッチの構造です。正常0件・失敗・処理段階により存在しないファイルがあります。旧単社runでは`private-runs/<run>/pdf/`等も使用します。公開専用releaseでは取得runとrelease-runが異なり、元の参照先をmanifestや継承証跡で辿ります。

PDF原本は証拠として、解析済み数値・文字列はSQLite等の構造化データとして、それぞれ保持します。manifestにPDFとevidenceのobject・generation・SHA-256、会社・対象設定・期待件数を記録します。`replay.py`は対象範囲・取得時刻・件数・参照先・SHA等を検証して保存済みPDFを読み戻す復旧用処理です。通常週次はfresh収集であり、replayを毎回の必須手順にはしません。

原本PDF総数、バケットのライフサイクル、実保存期間は今回未確認です。「永久保存」とは記載しません。private原本や解析行・認証情報をPagesへ公開しません。

## SQLiteの役割

| テーブル等 | 役割 |
| --- | --- |
| `buildings` | 恒久的canonical建物。既存ID・正式名・住所を保護 |
| `building_key_aliases` / `building_sources` | alias解決、入力証拠と建物の対応 |
| `listings` / `sale_listings` | 賃貸・分譲の別系統の募集と履歴 |
| `ingest_runs` / `current_ingest_snapshots` | 実行記録とソース別の現在有効run |
| `cloud_scope_bindings` / `cloud_baseline_ownership` | クラウド対象範囲と確認済み旧明細所有範囲 |
| `raw_sources` | 入力原文等のprivate履歴。PDFファイル自体の代替ではない |
| `building_summaries`等 | 有効snapshotを合成した公開向け集約（再生成可能） |

`listings`を単なる一時派生物として廃棄しません。履歴を保持し、公開集約はsource別currentを使用します。Ulucksのscopeは`ulucks:<scope-hash>`で、旧取り込みrunには`master_import`等もあります。すべてのsource名を`master_import`へ固定しません。

## 採用と公開の境界

高信頼な既存マッチ・新規auto-seedは正式採用、曖昧・異常行はprivate保留です。正式採用された非hidden建物を原則自動公開し、過去の公開DBを許可リストにしません。旧公開DBは既存IDの欠落検出用です。

検索・ページの統合は整合する明示的canonical aliasに限定します。名称・住所一致だけで別IDを消しません。募集0件でも建物は残し、失敗したソースのsnapshotを正常0件として置き換えません。

## ローカルファイルと例外修正

`data/tatemono_map.sqlite3`は開発・旧手動運用で使うパスで、クラウド本番の所在を意味しません。`data/canonical/buildings_master.csv`等のCSVは初回投入や手動補助入力であり、運用中のGCS正本に優先しません。

`data/public/public.sqlite3`はPages取得先または開発用公開スナップショット、`dist/`は配信生成物です。直接編集して本番修正としません。建物修正は[correction仕様](building_corrections_csv.md)の記録・dry-runを参考に、最新GCS正本・バックアップ・世代一致を前提とする別作業で行います。古いローカルDBのアップロードで代用しません。

詳細: [spec](spec.md)、[データ契約](data_contract.md)、[本番Runbook](runbook.md)、[履歴索引](archive/README.md)。
