# データフローと Source of Truth（運用メモ）

このページは、建物DB運用における **「どこが正本か / どこを直すべきか / どこを直接触ってはいけないか」** を、図なしで把握するための実務メモです。

## 1) 一言で分かる整理

- **正本（SoT）**
  - 建物正本: `data/tatemono_map.sqlite3` の `buildings`
  - 空室正本: `data/tatemono_map.sqlite3` の `listings`（ただし source ごとの current snapshot 合成で参照）
  - canonical入力正本: `data/canonical/buildings_master.csv`（canonical建物入力）
- **入力（weeklyの原材料）**
  - ZIP/PDF から生成する `tmp/pdf_pipeline/out/.../master_import.csv`
- **派生物（再生成される結果）**
  - `building_summaries`（`buildings` + current snapshot の `listings` から集約）
  - `data/public/public.sqlite3`（公開用スナップショット）
  - `dist/`（Pages配信用の生成物）
- **レビュー用（例外処理・監査）**
  - `tmp/review/new_buildings_*.csv`
  - `tmp/review/suspects_*.csv`
  - `tmp/review/unmatched_listings_*.csv`
- **直接触ってはいけない場所**
  - `data/public/public.sqlite3` と `dist/` を手修正しない（いずれも結果物）

---

## 2) 用語整理

- **canonical building**
  - canonicalとして確定管理する建物エンティティ。`buildings` の1行。
- **buildings**
  - 建物の正本テーブル。建物ID・canonical名/住所・建物属性を保持。
- **listings**
  - 空室明細テーブル。取り込みrunごとに `ingest_run_id` を持つ。
- **building_summaries**
  - 公開・検索向けの建物集約。current snapshot の空室を合成して `vacancy_count` 等を持つ。
- **public.sqlite3**
  - 公開専用DB。`publish_public` で main DB から必要最小限をコピーした派生物（SoTではない）。
- **canonical CSV**
  - `data/canonical/buildings_master.csv`。canonical建物入力の正本CSV。
- **alias**
  - `building_key_aliases`。表記ゆれ等の alias_key を canonical_key に解決する対応表。
- **building_sources**
  - `source + evidence_id -> building_id` の由来追跡テーブル。
- **master_import.csv**
  - weekly取り込みの入力CSV（ZIP/PDFパイプライン生成物）。
- **review CSV**
  - 例外行を人が確認するためのCSV（new_buildings / suspects / unmatched_listings）。
- **current snapshot**
  - `current_ingest_snapshots` で source ごとに選ばれた現在有効run。空室集計はこの集合を参照。

---

## 3) ファイル / テーブル対応（どれが何か）

### `data/tatemono_map.sqlite3`（main DB, SoT）

- `buildings`: 建物正本（canonical建物）
- `listings`: 空室明細正本（run単位で蓄積）
- `building_summaries`: 公開用集約（派生）
- `building_key_aliases`: 表記ゆれ吸収の対応表
- `building_sources`: 証拠IDと建物IDの対応（由来追跡）

### `data/public/public.sqlite3`（公開DB）

- main DB から生成する公開スナップショット。
- SoTではない。運用上は「作り直すもの」。

### `data/canonical/buildings_master.csv`（canonical入力）

- canonical建物を人手管理する入力正本CSV。
- 建物の手修正はまずここ（または canonical側入力）を直す。

### `tmp/pdf_pipeline/out/.../master_import.csv`（weekly入力）

- ZIP/PDFから生成される ingest 入力。
- `listings` 更新・新規候補検出（auto-seed判定含む）の入口。

### `tmp/review/*.csv`（例外処理/監査）

- `new_buildings_*.csv`: auto-seedで追加された建物の監査ログ
- `suspects_*.csv`: 曖昧で要確認な候補
- `unmatched_listings_*.csv`: 建物に解決できなかった明細

---

## 4) weekly 更新フロー（実務順）

1. ZIP/PDF を所定場所に置く。
2. PDFパイプラインで `master_import.csv` を作る。
3. `ingest_master_import` で `listings` を取り込み、必要時のみ高信頼新規建物を `buildings` へ auto-seed。
4. `building_summaries` を current snapshot 合成で再構築。
5. `publish_public` で `data/public/public.sqlite3` を更新。
6. `render.build` / Pages CI で `dist` を生成・公開。

補足:
- source ごとの current snapshot は QC を通った run のみ切り替える。
- `publish_public` 失敗時は current snapshot を戻し、公開状態を壊さない。

---

## 5) 重要ルール（このrepoの現行運用）

- 既存建物（canonical `buildings`）は消さない。
- 空室は source ごとの current snapshot から更新する。
- 新規建物の auto-seed は高信頼条件を満たす場合のみ。
- 怪しい行は review CSV に残して人手確認へ回す。
- `public.sqlite3` と `dist` は結果物。直接修正しない。

---

## 6) 重複・曖昧ケースの扱い

- **aliasで吸収するもの**
  - 表記ゆれ・別名として確信できるものは `building_key_aliases` で canonical に寄せる。
- **source evidence で追うもの**
  - どの入力根拠で建物に紐づいたかは `building_sources` で追跡する。
- **suspects / unmatched に落とすもの**
  - 曖昧一致・低信頼候補・解決不能行は review CSV に出力し、自動確定しない。
- **人が確認すべき場所**
  - `tmp/review/suspects_*.csv` と `tmp/review/unmatched_listings_*.csv` を優先確認し、必要に応じて canonical入力と alias を更新する。

---

## 7) 人が直すならどこか（運用者向け）

- **建物マスターの修正**
  - `data/canonical/buildings_master.csv`（または canonical入力ルート）を修正する。
- **表記ゆれ吸収の修正**
  - alias方針に従って `building_key_aliases` 側で吸収する。
- **由来確認**
  - `building_sources` と review CSV を見て証拠ID単位で追う。
- **直接触るべきでない結果物**
  - `data/public/public.sqlite3` / `dist/` は直接修正せず、ingest→publish→build で再生成する。
- **reviewで見るCSV**
  - 新規監査: `new_buildings_*.csv`
  - 要確認: `suspects_*.csv`
  - 未解決: `unmatched_listings_*.csv`

---

## 8) ありがちな誤解（FAQ）

- **Q. public DB は正本か？**
  - A. いいえ。`public.sqlite3` は公開用の派生スナップショットです。
- **Q. dist を直接直せばよいか？**
  - A. いいえ。`dist` はCIで再生成される成果物です。
- **Q. review CSV は未反映データそのものか？**
  - A. いいえ。例外・監査対象の抽出結果です。確定反映には人手判断が必要です。
- **Q. auto-seed された建物はどこで追うか？**
  - A. `new_buildings_*.csv`（`ingest_run_id` / `source_evidence_id` / `building_id`）と `building_sources` で追跡します。
