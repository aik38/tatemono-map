# Data Contract（取り込み項目と正規化）

## 取り込み元
- Gmailで届く「最新空室リンクURL」（承諾済みデータのみ）
- Ulucks smartlink_page の raw HTML（raw_sources に保存）

## 抽出する最小項目（PoC）
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
- 住所正規化 + 建物名（あれば）で一意

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

## 公開DB（privacy-safe）契約
- `scripts/publish_public.ps1` は公開DBに最低限 `buildings`, `building_summaries` を含める。
- `building_key_aliases` は main DB に存在する場合のみコピーする（任意）。
- DoD: 公開DBの `buildings` 件数が 0 の場合は異常終了する。
