# 調査メモ: building ページの `—` 多発と住所未表示

## 結論（コード静的読解ベース）
- render の building ページは `building_summaries` を主データ源にし、`listings` は「空室サマリー表」と更新時刻補完にのみ利用する。
- rent/area/layout/move_in が `—` になるのは、`building_summaries` 側の値が `NULL` / 空 / JSON不正のときに起こる実装。
- 住所は `building_summaries.address` のみを見ており、`postal_code` カラムは render でも aggregate でも参照していない。
- そのため住所未表示は「address が空」または「address が listings から building_summaries へ正しく集約されていない」ことが最有力。

## 補足
- この環境では `data/tatemono_map.sqlite3` 実ファイルが存在せず、実DBの `PRAGMA table_info` 実行は未実施。
- テーブル列定義は `ensure_building_summaries_table` の DDL を事実上の仕様として確認した。
