# listings の address/rent_yen/area_sqm/layout/move_in が空になる原因調査

## 結論（確定）
最も疑わしい 1 点は、`_extract_field()` が **「ラベル: 値」形式（コロン必須）だけ** を対象にしており、現行の smartview 詳細 HTML が `th/td` 分離などコロン無し構造だった場合に全項目が未抽出になること。

## 根拠
- 取り込み時の抽出処理は `_extract_listing_fields()` で、`住所/賃料/面積/間取り/入居時期` を `_extract_field()` で取得する。
- `_extract_field()` は `label\s*[:：]\s*(.+)` でマッチする実装のため、コロンが無い表示は一致しない。
- 一致しない場合:
  - `address` は `_normalize_address(None)` により `""`（空文字）になる。
  - `rent_yen` / `area_sqm` は `None`。
  - `layout` / `move_in` も `None`。
- その結果、`_upsert_listing()` でそのまま `listings` に保存される。

## 参考
- `tests/test_ulucks_smartlink.py` の抽出テストも `<div>住所: ...</div>` `<div>賃料: ...</div>` のようなコロン付き形式のみを前提にしている。
