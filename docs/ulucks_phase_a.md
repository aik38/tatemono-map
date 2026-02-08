# Ulucks Phase A（smartlink 一覧のみ）

## 目的
Phase A は **smartlink 一覧ページのみ** を巡回・解析して、建物サマリ（建物単位の空室集計）を作成します。`/view/smartview/<id>/` のリンクIDは抽出しますが、smartview 個別ページには遷移しません。

> 補足: 検証済み smartlink HTML には `google.com/maps` が含まれず、Google Maps リンクは smartview 側に存在する可能性が高いです。

## CLI

```bash
python -m tatemono_map.ingest.ulucks_smartlink_phase_a \
  --url 'https://.../view/smartlink/?link_id=REDACTED&mail=REDACTED' \
  --max-pages 20 \
  --sleep 0.5 \
  --timeout 15 \
  --retry 2 \
  --cache-dir data/_debug_ulucks_phase_a \
  --out-json data/ulucks_phase_a_summary.json \
  --out-csv data/ulucks_phase_a_summary.csv
```

保存済み HTML から解析する場合（推奨: REDACTED fixture / ローカル debug ファイル）:

```bash
python -m tatemono_map.ingest.ulucks_smartlink_phase_a \
  --html tests/fixtures/ulucks/smartlink_phase_a_page_1.html tests/fixtures/ulucks/smartlink_phase_a_page_2.html \
  --out-csv data/ulucks_phase_a_summary.csv
```

## 抽出項目（カード単位）
- `smartview_id`
- `building_title_raw`
- `building_name`（末尾の号室/室/階を正規化除去）
- `address`（所在地）
- `rent_yen`
- `area_m2`
- `layout`
- `updated_at`（カード内にある場合のみ）

## 集計項目（建物サマリ）
- group key: `(building_name, address)`（空白/句読点揺れを吸収）
- `vacancy_count`
- `rent_yen_min/max`
- `area_m2_min/max`
- `layouts`（重複排除済み配列）

## PII/機微情報ルール
- `mail` パラメータ、TEL/FAX、担当者、元付会社情報を出力に含めない。
- URL のログは `mail=REDACTED` 化して出力。
- 生HTMLを保存する場合は `data/_debug_ulucks_*.html` 配下を使用し、`.gitignore` で除外する。
- テスト fixture は REDACTED のみを保持する。
