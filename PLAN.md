# PLAN（方針の正本）

## 1. このプロジェクトの目的
- Google Maps / Street View と連携できる不動産データベースの「母艦」を作る。
- 自動化パイプライン（収集→整形→保存→公開）を安定運用し、LINE 等の営業導線へ接続する。
- 北九州はパイロット地域であり、将来的に他エリアへ横展開する。

## 2. MVP と拡張の位置づけ
### MVP（最優先）
- 賃貸空室データを継続投入できること。
- 建物単位の canonical DB（`buildings`）を維持できること。
- 週次更新が 1 コマンドで再現できること。

### 次フェーズ（拡張）
- 売買査定の比較導線。
- 解体比較のリード獲得導線。
- 地図/ストリートビューを使った意思決定 UI の強化。

## 3. 正本ポリシー（Canonical-first）
- 正本は DB の `buildings` テーブル。
- `canonical_name` / `canonical_address` など手動判断の結果は自動上書きしない。
- 自動処理は「listing 更新」「新規建物候補の追加」まで。
- 未確定データは review CSV に分離し、人手判断で反映する。

## 4. 役割分担
- README: 入口（何をするリポジトリか、最短コマンド）。
- PLAN: 目的・優先順位・意思決定ルール。
- spec: 守るべき仕様（公開範囲、禁止事項、更新方針）。
- runbook: 実運用手順（初回投入/週次更新/障害時対応）。
- wbs: フェーズと DoD の進捗管理。

## 5. PDCA（週次運用）
- Plan: review CSV と KPI から次週対応を Issue 化。
- Do: seed / weekly update / publish を実行。
- Check: 公開 DB・配信物・差分を確認。
- Act: ルール変更は PLAN/spec/runbook/wbs を同時更新。

## 6. WBS 優先順位
1. 起動と同期の安定化（setup / sync / push）。
2. canonical DB 運用の固定化（seed と weekly update）。
3. 公開導線の安定化（public DB / 静的出力）。
4. データ品質ループ（suspects / unmatched の継続解消）。
5. 地図・ストリートビュー連携の運用品質向上。
6. 売買査定 / 解体比較リード導線の追加。

## 7. 変更管理ルール
- 方針変更は PLAN を先に更新し、README/spec/runbook/wbs を整合させる。
- ドキュメントに矛盾がある場合は PLAN と spec を優先する。
