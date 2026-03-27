# Mansion Review listfacts Batch 2 調査メモ（2026-03-27）

対象: city_id=1639,1683,1641,1632,1651（行橋市 / 京都郡苅田町 / 中間市 / 直方市 / 宮若市）

## 結論（優先度順）

1. **address 抽出の正規表現が北九州市専用で、Batch 2 の市町村名を拾えない。**
   - list 側: `(?:福岡県)?北九州市...` 固定。北九州市以外は fallback 不可。
   - facts 側（list card）: 同じく `(?:福岡県)?北九州市...` 固定。
2. **facts モードでのカード走査が `li.property-detail-list-item` 固定で、list 側より selector が狭い。**
   - list 抽出は複数 selector で拾えるが、facts 追加抽出は固定 selector のため `all_facts_rows` が空になりやすい。
3. **detail URL へ降りて address 補完する処理は定義されているが、`run_crawl(..., mode="facts")` から未使用。**
   - `parse_detail_facts()` は存在するが実行パスなし。
4. **その結果、facts 生成は list 行フォールバックになり、空 address がそのまま `building_facts_*.csv` に出る。**
   - 空 address は matcher で `address_without_digits` になり、safe create 条件（`match.reason == "unmatched"`）を満たさず `not_high_confidence` skip へ流れる。

## 既知症状との整合

- `match_reason=address_without_digits` が 898 件: **空/数字なし address と一致**。
- `skip_reason=not_high_confidence` が 898 件: safe create が `match.reason == "unmatched"` 必須のため一致。
- `building_name/evidence_id はあるが address 空`: facts 生成フォールバック経路の挙動と一致。

## 最小修正案（listfacts 側のみ）

### 案1（最小・本命）
**address 欠損時のみ detail 再取得して address を補完する。**

- 変更箇所: `scripts/mansion_review_crawl_to_csv.py`
- 変更内容（最小）:
  - facts モードで list から作った FactsRow の `address` が空、または数字なしの場合のみ `detail_url` を fetch。
  - `parse_detail_facts()` を呼び、`address` のみ上書き（他項目は現行を維持しても可）。
  - fetch 回数は欠損行のみなので、全件 detail fetch より副作用が小さい。
- 期待効果:
  - Batch 2 の address 欠損を埋め、`address_without_digits` 連鎖を止める。
  - safe create 基準は緩めない（要件遵守）。

### 案2（運用ガード）
**ingest 前 QC に address 非空率 fail-fast を追加。**

- 変更箇所候補:
  - `scripts/run_mansion_review_listfacts_to_db.ps1`（実行前チェック）
  - もしくは `scripts/mansion_review_crawl_to_csv.py` の stats 出力時
- 変更内容（最小）:
  - city_id/kind ごとに `address_non_empty_rate` を算出。
  - しきい値（例 95%）未満なら ingest 実行前に停止。
- 期待効果:
  - 「created=0, unresolved全件」の事故を早期検知。

### 案3（可観測性のみ）
**city_id/kind ごとの address 充足率を stats.json に出力。**

- 変更箇所: `scripts/mansion_review_crawl_to_csv.py`
- 変更内容（最小）:
  - `stats["address_coverage"]` に `{kind, city_id, rows, address_non_empty, address_with_digits}` を追加。
- 期待効果:
  - Canary / Batch1 / Batch2 の差分を即時比較可能。

## 今回の推奨

- まず **案1 + 案3**（本命 + 観測）を先行。
- その後、運用で事故防止が必要なら **案2** を追加。
- いずれも Mansion Review listfacts 経路だけで完結し、フロント・URL・公開物には非影響。
