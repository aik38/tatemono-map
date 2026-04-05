# 門司区 canary 基準点確認（cleanup後）

- 実施日: 2026-04-05
- 目的: 既存項目（賃貸/分譲/共通）が壊れていないかを **A/B/C** で切り分け、次段階の比較基準を固定する。
- 非対象: 管理費/共益費、敷金、礼金、向き、修繕積立金、総戸数、管理方式、所在階。

## 今回の確認範囲

- 【賃貸】賃料 / 間取り / 面積
- 【分譲】価格 / 間取り / 面積
- 【共通】築年月 / 構造

## 確認方法（軽量）

フル再実行は行わず、既存の `data/public/public.sqlite3` とそこからの静的出力のみを利用。

1. 門司区の代表建物を抽出（賃貸2件・分譲1件）。
2. A: source相当（public入力として使われる値）を `building_summaries` で確認。
3. B: `dist/data/buildings.v2.min.json` への反映を確認。
4. C: `dist/b/*.html` の表示を確認。

> 補足: `render.build` の JSON出力は `building_summaries` 由来のキーをそのまま payload に載せる実装。

## 代表建物（門司区 canary）

- 賃貸: シャトレ柳町
- 賃貸: レオネクストKUZUHA
- 分譲: サンライフ清見

## A/B/C 判定結果

### 1) 賃貸（賃料 / 間取り / 面積）

- A（source相当）
  - シャトレ柳町: `rent_yen_min=35000`, `layout_types_json=["1K"]`, `area_sqm_min=21.0`
  - レオネクストKUZUHA: `rent_yen_min=40000`, `layout_types_json=["1K","1R"]`, `area_sqm_min=26.09`
- B（DB→JSON）
  - `rent_min`, `room_types`, `area_min` として `dist/data/buildings.v2.min.json` に反映。
- C（front）
  - 建物詳細で「賃料」「間取り」「面積」が表示されることを確認。

判定: **OK（壊れていない）**。

### 2) 分譲（価格 / 間取り / 面積）

- A（source相当）
  - サンライフ清見: `sale_price_yen_min=11600000` は有値。
  - ただし `sale_layout_types_json` と `sale_area_sqm_min` は空/NULL。
- B（DB→JSON）
  - `sale_price_min` は反映される。
  - `sale_layout_types` / `sale_area_min` は NULL/空のまま。
- C（front）
  - 「価格」は表示される（例: 1,160万円）。
  - 「間取り」「面積」は `要確認` 表示（値欠損時の既定表示）。

判定: **価格はOK、間取り/面積は canary 時点で欠損が基準状態**。

### 3) 共通（築年月 / 構造）

- A（source相当）
  - 3建物とも `building_built_year_month` / `building_structure` に値あり。
- B（DB→JSON）
  - `building_built_year_month` / `building_structure` が `dist/data/buildings.v2.min.json` に反映。
- C（front）
  - 建物詳細で「築年月」「構造」が表示されることを確認。

判定: **OK（壊れていない）**。

## 壊れている箇所がある場合の最小原因

今回、既存安定項目のうち明確に注意が必要なのは **分譲の間取り/面積**。

- フロントは欠損時に `要確認` を出す仕様（表示崩れではない）。
- 実データ側で `sale_layout_types_json` / `sale_area_sqm_min` が未充足のため、結果として `要確認` になる。

最小原因: **入力値欠損（source相当段階で未充足）**。

## 基準点としての短い整理（freeze）

- 賃貸3項目（賃料・間取り・面積）は、門司区 canary の代表建物で A/B/C すべて整合。
- 分譲3項目は、
  - 価格: A/B/C 整合
  - 間取り・面積: A欠損 → B欠損 → C `要確認`（現状仕様どおり）
- 共通2項目（築年月・構造）は A/B/C 整合。

したがって、**2026-04-05 時点の基準点**は以下:

1. 賃貸項目は現状維持で正常。
2. 分譲の間取り/面積は「未投入（要確認表示）」が現行ベースライン。
3. 以降の追加実装では、このベースライン差分としてのみ評価する。

## 次段階で触ってよい最小ファイル（提案）

追加項目に入る次段階で、影響を最小化するなら以下の順で限定:

1. `scripts/mansion_review_list_to_master_import.py`
   - 一覧CSV→master_import変換で `layout` / `area_sqm` を作る入口。
2. `src/tatemono_map/building_registry/ingest_building_facts.py`
   - facts取り込みと building/building_summaries 反映の中核。
3. `src/tatemono_map/render/build.py`
   - public DB→`dist/data/*.json` の写経部（キー反映確認）。
4. `tests/test_mansion_review_list_to_master_import.py` / `tests/test_ingest_building_facts.py`
   - 既存項目の回帰防止。

※ templates/CSS/JS/CTA/SEO は今回方針どおり触らない。
