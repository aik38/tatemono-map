# Data Contract（取り込み項目と正規化）

## 現行クラウド契約（2026-10-19 JST）

本番正本はGCS `state/current.json`が指すSQLiteです。Ulucks全社・北九州全域のfresh取得PDFとmanifest/evidenceをprivate GCSへ保存し、解析・名寄せ・QC後の正式採用データを正本へ反映します。PDF原本保存とSQLiteへの数値・文字列保存は両立します。原本総数・ライフサイクル・保存期間は今回未確認です。

- canonical ID・既存正式名・住所・URL・履歴を保護し、名称/住所一致だけで別IDを確定統合しません。alias/evidenceと既存マッチガードを使用します。
- 高信頼auto-seedを正式採用し、曖昧・異常な未採用行はprivate保留。解析行数と採用数を同一視しません。
- 正式採用の非hidden建物は原則自動公開。`hidden_from_public`以外に旧公開DBによる許可リストを設けません。
- 公開DBは`buildings`/`building_summaries`が必須、存在する場合のalias・賃貸/分譲集約だけを許可します。private明細・raw・PDF・認証情報を混ぜません。
- `publication_ids`で公開DB ID集合、`rendered_ids`で整合する明示的canonical alias統合後の検索/ページID集合を定義し、marker・JSON等で検証します。文字列一致だけの検索除外はしません。
- 賃貸優先順位Ulucks ＞ RealPro ＞ Mansion Review賃貸、分譲独立、source別current snapshot合成、失敗≠正常0件の契約を維持します。
- 賃貸順位は建物単位のソース採用で、項目別の混合ではありません。全行に明示的順位がある場合に最優先を選び、未順位legacy行の混在時は既存の合成snapshot方針を維持します（`effective_rentals`）。

詳細は[spec](spec.md)、[データフロー](data_flow_and_sources_of_truth.md)。以下のPDF/CSV・旧HTMLルートの項目定義は互換・手動補助契約です。クラウド経路でCSVの手動作成を必須にはしません。

## 既存HTML・メール入力（互換/手動補助）
- Gmailで届く「最新空室リンクURL」（承諾済みデータのみ）
- Ulucks smartlink_page の raw HTML（raw_sources に保存）

## 旧PoCの最小抽出項目（互換参照）
- 建物名（あれば）
- 住所（あれば）
- 間取りタイプ（1Kなど）
- 家賃
- 共益費（あれば）
- 面積
- 入居可能日（即入居/日付/上旬など）
- 更新日時（ページ/メール日時など）

## 正規化
- 空室ステータス（公開）：空室あり / 満室（空き予定は空室ありに含める）
- 住所は都道府県プレフィックス（例: 福岡県/東京都/北海道）を比較時に無視し、市区町村以下を一致キーとして扱う。

## 建物キー
- 住所・建物名の正規化は候補照合の入力です。恒久的な同一性はcanonical IDとalias/evidenceで管理し、名称・住所だけで異なるIDを統合しません。

## 位置情報（緯度・経度）
- MVPでは必須ではない（任意）。
- 住所がある場合は後続フェーズでジオコードする前提とし、取得できる場合のみ lat/lon を保持する。


## PDF batch pipeline 項目定義（Vacancy専用: Ulucks/Realpro）
- final.csv 必須列:
  - `category,updated_at,building_name,room,address,rent_man,fee_man,layout,floor,area_sqm,age_years,structure,file,page,raw_block,evidence_id`
- 互換列（必要時のみ）:
  - `--legacy-columns` 指定時に `source_property_name`,`room_no`,`raw_blockfile` を追加出力

補足:
- `A棟/B棟/◯号棟` 等の棟表記は `building_name` として保持し、QCで誤検知しない。
- 戸建（戸建/一戸建/貸家/一軒家）は行単位で除外し、PDF全体は処理継続する。
- QCモードは `warn`（既定）/`strict`/`off`。停止は `strict` のみ。


## master_import.csv スキーマ契約
- `master_import.csv`（週次PDF pipeline成果物）の公式ヘッダ（v1）は次の16列・順序固定とする。
  - `category,updated_at,building_name,room,address,rent_man,fee_man,layout,floor,area_sqm,age_years,structure,file,page,raw_block,evidence_id`
- 文字コードは `UTF-8 with BOM`（`utf-8-sig`）を正式仕様とする。
- `scripts/run_pdf_zip.ps1` / `scripts/run_pdf_zip_latest.ps1` が生成する `master_import.csv` は、上記 v1（`src/tatemono_map/cli/pdf_batch_run.py` の `FINAL_SCHEMA`）を満たすこと。
- ingest 側（`src/tatemono_map/building_registry/ingest_master_import.py`）の受け入れヘッダ:
  - 15列（標準）: `page,category,updated_at,building_name,room,address,rent_man,fee_man,floor,layout,area_sqm,age_years,structure,raw_block,evidence_id`
  - 14列（互換/legacy）: 上記から `evidence_id` を除いた形式
  - 16列（公式 v1 / pdf final互換）: `category,updated_at,building_name,room,address,rent_man,fee_man,layout,floor,area_sqm,age_years,structure,file,page,raw_block,evidence_id`
- 15列/14列は互換受理のため残している legacy 扱いであり、将来的に非推奨とする。
- 16列フォーマットでは `file` は追跡用途の補助列として扱い、ingest時は listings 正規化の必須項目に影響しない。

## 既存PowerShell公開DBの互換契約（クラウドではpublic_db.pyを使用）
- `scripts/publish_public.ps1` は公開DBに最低限 `buildings`, `building_summaries` を含める。
- `building_key_aliases` は main DB に存在する場合のみコピーする（任意）。
- DoD: 公開DBの `buildings` 件数が 0 の場合は異常終了する。


## age_years / structure の契約（master_import → listings → building_summaries → UI）
- `master_import.csv` の `age_years` / `structure` は、列が存在しない・値が欠損している場合でも ingest は継続し、`NULL` として扱う。
- `listings` には観測値として `age_years`（INTEGER）/ `structure`（TEXT）を保存する。
- `building_summaries` では建物単位の代表値を保持する。
  - `age_years`: 欠損除外後に最頻値（mode）。同率なら中央値（median, 偶数件は中央2値の平均を整数化）で決定。
  - `structure`: 欠損除外後に最頻値（mode）。同率なら辞書順の先頭を採用。
- `scripts/publish_public.ps1` は `building_summaries` を public DB にコピーするため、`age_years` / `structure` も公開DBへ反映される。
- Web UI（建物詳細）は `building_summaries.age_years` / `building_summaries.structure` を表示し、欠損時は `—` を表示する。

## 建物マスター系ルート（Mansion-review / Orient）契約
- 建物一覧ルート（空室単位 listings を持たないルート）は `buildings` に建物属性を保存する。
  - `structure` (TEXT)
  - `age_years` (INTEGER)
  - `built_year` (INTEGER)
  - `availability_raw` / `availability_label` (TEXT, NULL許容)
- `building_summaries` 集約時は次を適用:
  - `structure` / `age_years` / `building_built_*`: listings 優先、欠損時に `buildings` フォールバック
  - `building_availability_label`: listings が存在する建物のみ計算。空室0建物は NULL
