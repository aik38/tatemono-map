# spec（運用仕様の正本）

## 1. システム定義
このシステムは、Google Maps / Street View（ストリートビュー）と連携可能な不動産データベース母艦です。  
北九州はパイロット地域であり、対象地域は将来拡張されます。

## 2. 目的
- 建物単位で情報を統合し、媒体差分に強いデータ基盤を維持する。
- 週次更新を定型化して、運用の属人化を減らす。
- MVP は賃貸空室に集中し、将来は売買査定/解体比較導線へ拡張する。

## 3. Canonical source of truth（正本）
- 正本は SQLite DB の `buildings` テーブル（唯一の正本）。
- `listings` / `building_summaries` / `data/public/public.sqlite3` はすべて派生物。
- canonical 項目（`canonical_name`, `canonical_address`）は seed/weekly のどちらでも自動上書きしない。

## 4. ロール分割（責務）
- 自動処理の責務
  - listing の取り込み・正規化・突合（match）。
  - 新規建物候補の追加（既存 canonical の破壊は禁止）。
  - 公開用データ（public DB / 静的出力）の更新。
- 人手判断の責務
  - canonical 項目の確定・修正。
  - review CSV（`new_buildings` / `suspects` / `unmatched_listings`）のトリアージ（優先度判断）。
  - 運用ルールの変更承認。

## 5. 公開サマリー項目（最低限）
- 建物ID（`building_id`）と建物名（canonical）。
- 住所/座標（確定済み canonical 値）。
- 空室関連の派生情報（最新更新日を含む）。
- データ更新時刻と生成元のトレーサビリティ（追跡可能性）。

## 6. 禁止事項
- `buildings_master` の再構築を現行運用の正規フローに戻すこと。
- canonical 項目をバッチで自動上書きすること。
- review 未解決データを確定値として公開反映すること。

## 7. 週次運用ポリシー
- 週次は 1 コマンドで再現可能であること。
- 週次は `buildings` を再構築しない（既存を維持しつつ、必要な新規のみ追加）。
- 不明データがあっても処理は継続し、review CSV に必ず出力する。

## 8. 更新ポリシー
- 仕様変更時は、PLAN → spec → runbook/README/wbs の順で整合更新する。
- 週次運用で発見した例外は runbook に追記し、恒久ルール化する場合は spec に昇格する。
- 矛盾が出た場合は PLAN と本 spec を優先し、README は入口情報として追随する。
