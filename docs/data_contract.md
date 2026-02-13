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

## 建物キー
- 住所正規化 + 建物名（あれば）で一意

## 位置情報（緯度・経度）
- MVPでは必須ではない（任意）。
- 住所がある場合は後続フェーズでジオコードする前提とし、取得できる場合のみ lat/lon を保持する。


## PDF batch pipeline 項目定義（Vacancy専用: Ulucks/Realpro）
- final.csv 必須列:
  - `category,updated_at,building_name,room,address,rent_man,fee_man,layout,floor,area_sqm,age_years,structure,file,page,raw_block`
- 互換列（必要時のみ）:
  - `--legacy-columns` 指定時に `source_property_name`,`room_no`,`raw_blockfile` を追加出力

補足:
- `A棟/B棟/◯号棟` 等の棟表記は `building_name` として保持し、QCで誤検知しない。
- 戸建（戸建/一戸建/貸家/一軒家）は行単位で除外し、PDF全体は処理継続する。
- QCモードは `warn`（既定）/`strict`/`off`。停止は `strict` のみ。
