# `building_corrections.csv` 仕様（手動レビュー教師データ）

## 1. 役割（このCSVを何に使うか）

`tmp/manual/building_corrections.csv` は、フロントエンド確認・目視レビュー・手動検証で見つけた建物情報の誤りを記録するCSVです。  
このCSVは「公開用JSON / dist を直接直すための台帳」ではなく、**正本DB修正や正規化改善の入力データ**として扱います。

このCSVの目的は次の3つです。

1. **正本DB修正のためのレビュー記録**
   - 建物名や住所の誤記を後から再現できる形で残す
   - 場当たり的な手修正ではなく、「何をどう直したいか」を履歴として保存する
2. **名寄せ・重複候補レビューの補助**
   - 修正後に同一建物となりそうな候補をレビューしやすくする
   - すぐ統合せず、判断材料として残す
3. **将来の誤記分析・補正ルール化の教師データ**
   - ソース別・誤りタイプ別の傾向を集計可能にする
   - 収集時 / 正規化時の補正ルール化につなげる

> 現時点では、CSVは ChatGPT や人手で作成・追記して構いません。専用の create スクリプトは不要です。

---

## 2. 運用原則

- **1行 = 1修正**
- 1つの建物に「建物名修正」と「住所修正」がある場合は、**2行に分けて記録**する
- すぐ自動反映する前提ではなく、レビュー・分析・後続反映のために残す
- `old_value` は可能な限り記載する
- `new_value` には「修正後にしたい値」を記載する
- 不確実な修正は `status=pending` とし、`note` に根拠・保留理由を残す
- 対象が曖昧な修正は、曖昧なまま適用しない
- 住所の番地まで不明な場合は、分かる範囲のみ `new_value` に書き、`note` に「枝番未確認」等を明記する
- このCSVは履歴・教師データであり、公開生成物を直接上書きする用途には使わない

---

## 3. 標準カラム定義

### 3.1 必須列

| 列名 | 説明 | 例 |
|---|---|---|
| `status` | 修正状態 | `pending`, `approved`, `applied`, `rejected` |
| `action` | 行の目的 | `fix`, `review_duplicate`, `merge_candidate`, `drop_duplicate_loser` |
| `target_building_name` | 対象建物を特定するための名称 | `Cotto九工大前` |
| `target_address` | 対象建物を特定するための住所（補助キー） | `福岡県北九州市小倉北区中原西3-4-3` |
| `field` | 何を直すか | `building_name`, `address` |
| `old_value` | 現在の値（誤り側） | `コンフォートプレイス小 倉` |
| `new_value` | 修正後にしたい値 | `コンフォートプレイス小倉` |
| `note` | 根拠・補足（自由記述） | `区名誤り（フロント確認）` |

### 3.2 分析用途で強く推奨する列

| 列名 | 説明 | 例 |
|---|---|---|
| `source` | 誤記が見つかった元ソース / 由来 | `frontend`, `ulucks_pdf`, `realpro_pdf`, `manual_import`, `unknown` |
| `error_type` | 誤りタイプ分類（できるだけ定義済み値を使う） | `ward_mismatch`, `building_name_spacing` |

### 3.3 任意列

| 列名 | 説明 | 例 |
|---|---|---|
| `reviewer` | 発見者 / 記録者 | `akira`, `chatgpt` |
| `reviewed_at` | 記録日（ISO推奨） | `2026-03-08` |
| `confidence` | 修正確度 | `high`, `medium`, `low` |
| `canonical_building_id` | 将来の正本ID紐付け | `bld_12345` |
| `duplicate_group` | 重複候補グループ識別子 | `dup_2026_03_08_01` |

---

## 4. 最小実用列セット（現時点の推奨）

当面の標準は次の10列です。

1. `status`
2. `action`
3. `target_building_name`
4. `target_address`
5. `field`
6. `old_value`
7. `new_value`
8. `note`
9. `source`
10. `error_type`

理由:

- 手動修正運用として軽量
- 将来の分析に必要な最低限の情報を保持
- `source` / `error_type` があるだけで、ソース別の壊れやすさと誤記傾向を集計しやすい

---

## 5. 値の定義

### 5.1 `status`

- `pending`: 気づいたがレビュー・反映前
- `approved`: レビュー済みで妥当
- `applied`: 正本DBまたは運用側へ反映済み
- `rejected`: 誤認・根拠不足等で却下

### 5.2 `action`

- `fix`: 値の修正指示
- `review_duplicate`: 同一建物の可能性がありレビュー待ち
- `merge_candidate`: 同一建物として統合候補（未確定）
- `drop_duplicate_loser`: 重複の負けレコードを正本DBに残したまま公開対象から除外

> 当面の主運用は `fix`・`review_duplicate`・`drop_duplicate_loser`。

### 5.3 `error_type` 候補

- `ward_mismatch`: 区名の誤り（例: 小倉北区 / 戸畑区の取り違え）
- `building_name_spacing`: 建物名中の不要空白
- `prefecture_prefix_variation`: `福岡県` の有無などの表記揺れ
- `address_incomplete`: 番地不足、枝番未確認
- `address_format_variation`: ハイフン有無・全角半角揺れ
- `alias_or_duplicate_candidate`: 別名義・別表記だが同一建物の可能性

---

## 6. 記入ルール（将来スクリプトが読みやすい形）

### 6.1 1行1修正の厳守

- 1行で複数 `field` を同時に直さない
- 同一建物で修正点が複数ある場合は行を分ける

### 6.2 文字列の書き方

- `old_value` / `new_value` は比較しやすいよう、不要な説明文を入れず値そのものを書く
- 原則として前後空白は入れない
- 迷った場合は `note` に判断根拠を追記する

### 6.3 空欄ルール

- 必須列は空欄禁止（ただし `target_address` は住所情報が元データに無い場合のみ空欄可）
- `review_duplicate` / `merge_candidate` / `drop_duplicate_loser` で値差分がない場合、`field` / `old_value` / `new_value` は空欄可
- 任意列は未使用なら空欄でよい

### 6.4 レビュー時の注意

- 対象が曖昧なら `pending` のままにし、特定できる根拠が揃うまで `approved` に進めない
- 住所が不完全なら、分かる範囲のみ記録して `note` で不足点を明記する
- `rejected` は誤修正防止に重要な履歴なので削除せず残す

---

## 7. 例（そのまま使えるサンプル）

```csv
status,action,target_building_name,target_address,field,old_value,new_value,note,source,error_type
pending,fix,Cotto九工大前,福岡県北九州市小倉北区中原西3-4-3,address,福岡県北九州市小倉北区中原西3-4-3,北九州市戸畑区中原西3-4-3,区名誤り（フロント確認）,frontend,ward_mismatch
pending,fix,コンフォートプレイス小 倉,,building_name,コンフォートプレイス小 倉,コンフォートプレイス小倉,建物名の不要空白,frontend,building_name_spacing
pending,fix,CITRUS TREE,北九州市小倉南区足立,address,北九州市小倉南区足立,北九州市小倉北区足立,区名は要補正・枝番未確認,frontend,address_incomplete
pending,review_duplicate,ザ・サンパーク小倉駅タワーレジデンス,北九州市小倉北区浅野2-18-3,,,,修正後に既存建物と同一の可能性あり,frontend,alias_or_duplicate_candidate
approved,drop_duplicate_loser,ニューシティアパートメンツ南小倉II,福岡県北九州市小倉北区東篠崎3,,,,空室0件・家賃0円レンジの重複負けレコードを公開から除外,frontend,alias_or_duplicate_candidate
```

同内容のサンプルは `docs/examples/building_corrections.sample.csv` も参照してください。

---

## 8. 将来の活用（想定する分析）

このCSVを蓄積すると、次の分析スクリプトを実装しやすくなります。

- `source` 別の誤記件数・誤記率集計
- `error_type` 別の頻出パターン抽出
- `status` 遷移（pending→approved→applied）滞留分析
- `review_duplicate` の件数推移と優先レビュー候補抽出

これらは、収集処理や正規化処理へのルール追加優先度の判断材料になります。


## 9. 安全反映CLI（`apply_building_corrections`）

手動修正CSVを正本DBに安全適用するため、`tatemono_map.cli.apply_building_corrections` を使えます。

```bash
python -m tatemono_map.cli.apply_building_corrections   --db data/tatemono_map.sqlite3   --corrections tmp/manual/building_corrections.csv
```

- 既定は **dry-run**（更新しない）で、結果CSVと重複候補CSVだけを `tmp/manual/outputs/` に出力します。
- 実更新は `--apply` 指定時のみ行います。
- `old_value` と実DB値が一致しない行は保留します。
- `CITRUS TREE` の `address_incomplete`（note に「枝番未確認」等を含む）は既定で保留します。
  - 明示的に進める場合のみ `--allow-incomplete-address` を指定します。


### 9.1 `drop_duplicate_loser` の最小運用

- `target_building_name` + `target_address` で**負けレコードを1件特定**します。
- `action=drop_duplicate_loser` 行は、`buildings.hidden_from_public=1` を設定します（物理削除しません）。
- 以後の `build_dist_versions` / `export_buildings_json` では `hidden_from_public=1` が公開JSONに出なくなります。
- 取り消す場合はDBで `hidden_from_public=0` に戻すか、同じ建物を別CSVで復帰ルール化してください。
