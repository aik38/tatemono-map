# WBS（Phase 0-6）

本書は PLAN/spec/runbook に基づく工程管理の正本です。  
各 Phase は「完了条件（DoD）」と「制約」を満たした時点でクローズします。

## 共通制約
- Canonical source of truth は `buildings` テーブル。
- manual 決定済み canonical 値の自動上書きは禁止。
- 北九州はパイロット。地域依存のハードコードは避ける。

## Phase 0: Onboarding/入口整備
- README をコピー&ペースト可能な入口に整備。
- docs index（読む順序）を固定。
- PLAN/spec/wbs の整合確認。

**DoD**
- README から setup/sync/push/weekly_update を実行できる。
- docs/README.md から主要文書へ迷わず遷移できる。

## Phase 1: Canonical data foundation
- seed 入力の品質確認。
- `buildings` 中心のデータモデルを固定。
- 手動確定項目の保護ルールを運用に反映。

**DoD**
- seed 再実行で重複投入しない。
- canonical 項目が自動更新されない。

## Phase 2: Weekly operation stabilization
- `weekly_update` の定常運用を確立。
- review CSV（new/suspects/unmatched）の確認導線を固定。

**DoD**
- 週次1コマンドで public DB と配信用成果物が更新される。
- 未解決データが review CSV へ必ず分離される。

## Phase 3: Public delivery reliability
- 公開データの品質ゲート運用。
- 地図/ストリートビュー連携の前提データを整備。

**DoD**
- 公開サマリー項目が欠損なく出力される。
- 更新時刻/由来情報の追跡が可能。

## Phase 4: Data quality loop（継続改善）
- suspects/unmatched の解消サイクルを継続。
- alias/evidence の蓄積ルールを運用化。

**DoD**
- 未解決率を週次でトラッキングできる。
- 再発パターンに対する改善施策が runbook に反映される。

## Phase 5: Maps/StreetView + LINE lead integration
- 地図導線と営業導線の接続仕様を策定。
- LINE 連携向けのイベント/属性設計を段階導入。

**DoD**
- 建物単位で地図閲覧→問い合わせ導線が成立。
- 連携イベントが追跡可能で、運用監視できる。

## Phase 6: Expansion（売買査定/解体比較）
- 賃貸以外ユースケースへの拡張。
- 売買査定比較・解体比較の lead-gen モデルを実装。

**DoD**
- 賃貸MVPと競合しない拡張設計が確立。
- 主要KPI（獲得数/転換率）を測定できる。
