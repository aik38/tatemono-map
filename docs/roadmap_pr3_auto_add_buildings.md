# PR3ロードマップ：unmatched からの建物自動追加（将来）

## 現状（MVP運用）
- ingest は `buildings` にマッチした空室のみ `listings` へ取り込む。
- unmatched は `tmp/review/unmatched_listings_*.csv` に出力して、現時点では取り込まない（捨てる）。
- 理由は MVP ローンチと収益化の優先。精度追い込みで公開を遅らせない。

## 理想像（PR3）
- 空室行が unmatched の場合でも、条件を満たせば `buildings` に新規追加する。
- 追加した建物へ空室を紐づけ、公開UIに表示できる状態まで自動化する。
- ただし既存建物への誤マッチ増加は許容しない（安全側運用）。

## 安全条件（ガード案）
- `normalized_address` が空、または短すぎる（例: 市区町村未満）の場合は自動追加しない（`needs_review` へ）。
- 重複防止として `normalized_name + normalized_address` のユニーク制約相当チェックを通す。
- 建物 provenance を識別できるフラグを付与する（例: `source_kind=vacancy_only`）。

## PDCA（再開時の進め方）
- unmatched を住所/建物名/ソース別に定期集計し、上位から改善対象を選定する。
- 既存建物へのマッチ改善（正規化・alias）と、新規建物自動追加（PR3）を分離して検証する。
- 週次で `attached_listings` / `unresolved` / reason 内訳を比較し、悪化時は即ロールバックする。

## 成果指標
- `unresolved` の削減目標を設定する（例: 706 → 300）。
- 取り込み件数増と誤マッチ率（人手レビュー件数増）をセットで評価する。
- `source_kind=vacancy_only` の建物が後続レビューでどれだけ正規化できたかを追跡する。
